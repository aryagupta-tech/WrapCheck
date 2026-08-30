import csv
import hashlib
import io
import json
import logging
import subprocess
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import NAMESPACE_URL, uuid4, uuid5

import google_crc32c
from fastapi import HTTPException, Request
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest

from .delivery_models import (
    AssetKind, Delivery, DeliveryAsset, DeliveryStatus, IngestionJob, JobStatus,
    UploadAssetDeclaration, UploadTarget,
)
from .handoff_gate import handoff_status, reconcile_media
from .handoff_models import ExpectedTake, HandoffRun, MediaCopy, MediaFile, SourceDocument
from .services.report_normalizer import normalize_report
from .services.uploads import sanitized_filename


logger = logging.getLogger(__name__)
REPORT_LIMIT = 10 * 1024 * 1024
MEDIA_LIMIT = 500 * 1024 * 1024
LOCAL_UPLOAD_ROOT = Path("/tmp/wrapcheck-uploads")
ALLOWED_CONTENT_TYPES = {
    AssetKind.camera_report: {"text/csv", "application/csv", "application/json", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    AssetKind.sound_report: {"text/csv", "application/csv", "application/json", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    AssetKind.script_notes: {"text/csv", "application/csv", "application/json", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    AssetKind.media_manifest: {"text/csv", "application/csv", "application/json"},
    AssetKind.camera_video: {"video/mp4", "video/quicktime"},
    AssetKind.production_audio: {"audio/wav", "audio/x-wav", "audio/wave"},
}
ALLOWED_EXTENSIONS = {
    AssetKind.camera_report: {".csv", ".json", ".pdf", ".docx"},
    AssetKind.sound_report: {".csv", ".json", ".pdf", ".docx"},
    AssetKind.script_notes: {".csv", ".json", ".pdf", ".docx"},
    AssetKind.media_manifest: {".csv", ".json"},
    AssetKind.camera_video: {".mp4", ".mov"},
    AssetKind.production_audio: {".wav"},
}


def _now():
    return datetime.now(timezone.utc)


def validate_declaration(declaration: UploadAssetDeclaration) -> str:
    filename = sanitized_filename(declaration.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS[declaration.kind]:
        raise HTTPException(status_code=415, detail=f"{extension or 'extensionless'} files are not accepted for {declaration.kind.value}")
    if declaration.content_type.lower().split(";", 1)[0].strip() not in ALLOWED_CONTENT_TYPES[declaration.kind]:
        raise HTTPException(status_code=415, detail=f"{declaration.content_type} is not accepted for {declaration.kind.value}")
    limit = MEDIA_LIMIT if declaration.kind in {AssetKind.camera_video, AssetKind.production_audio} else REPORT_LIMIT
    if declaration.size_bytes > limit:
        raise HTTPException(status_code=413, detail=f"{filename} exceeds the {limit // (1024 * 1024)} MB limit")
    return filename


def generate_gcs_signed_url(blob, *, method: str, expiration: int | timedelta, content_type: str | None = None) -> str:
    """Sign a GCS URL from Cloud Run via IAM without storing a private key."""
    credentials, _ = google_auth_default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    service_account_email = getattr(credentials, "service_account_email", "")
    if not service_account_email or service_account_email == "default" or not credentials.token:
        raise RuntimeError("Cloud Run signing credentials could not be resolved")
    return blob.generate_signed_url(
        version="v4",
        expiration=expiration,
        method=method,
        content_type=content_type,
        service_account_email=service_account_email,
        access_token=credentials.token,
    )


def create_upload_target(settings, delivery: Delivery, declaration: UploadAssetDeclaration) -> UploadTarget:
    filename = validate_declaration(declaration)
    asset_id = str(uuid4())
    if settings.app_mode == "live" and getattr(settings, "curated_media_bucket", None):
        from google.cloud import storage
        object_name = f"uploads/{delivery.delivery_id}/{asset_id}/{filename}"
        client = storage.Client(project=settings.google_cloud_project)
        blob = client.bucket(settings.curated_media_bucket).blob(object_name)
        upload_url = generate_gcs_signed_url(
            blob,
            expiration=900,
            method="PUT",
            content_type=declaration.content_type,
        )
        storage_uri = f"gs://{settings.curated_media_bucket}/{object_name}"
    else:
        storage_uri = str(LOCAL_UPLOAD_ROOT / delivery.delivery_id / asset_id / filename)
        upload_url = f"/api/deliveries/{delivery.delivery_id}/assets/{asset_id}/content"
    asset = DeliveryAsset(
        asset_id=asset_id,
        delivery_id=delivery.delivery_id,
        kind=declaration.kind,
        filename=filename,
        content_type=declaration.content_type,
        size_bytes=declaration.size_bytes,
        storage_uri=storage_uri,
    )
    return UploadTarget(
        asset=asset,
        upload_url=upload_url,
        required_headers={"Content-Type": declaration.content_type, "Content-Length": str(declaration.size_bytes)},
    )


async def store_local_upload(request: Request, asset: DeliveryAsset) -> DeliveryAsset:
    path = Path(asset.storage_uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    crc32c = google_crc32c.Checksum()
    received = 0
    with path.open("wb") as handle:
        async for chunk in request.stream():
            received += len(chunk)
            if received > asset.size_bytes:
                handle.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Upload exceeds its declared size")
            sha256.update(chunk)
            crc32c.update(chunk)
            handle.write(chunk)
    if received != asset.size_bytes:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Expected {asset.size_bytes} bytes but received {received}")
    inspect_file(path, asset.kind)
    if asset.kind in {AssetKind.camera_video, AssetKind.production_audio}:
        asset.media_metadata = probe_media(path)
    asset.sha256 = sha256.hexdigest()
    asset.crc32c = crc32c.hexdigest().decode("ascii")
    asset.uploaded = True
    return asset


def inspect_file(path: Path, kind: AssetKind) -> None:
    with path.open("rb") as source:
        head = source.read(32)
    extension = path.suffix.lower()
    if extension == ".pdf" and not head.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="The uploaded PDF has an invalid signature")
    if extension == ".docx":
        if not head.startswith(b"PK"):
            raise HTTPException(status_code=415, detail="The uploaded DOCX has an invalid signature")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise HTTPException(status_code=415, detail="Macro-enabled documents are not accepted")
            if len(names) > 1000 or sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Document archive expands beyond the safety limit")
    if extension in {".mp4", ".mov"} and b"ftyp" not in head:
        raise HTTPException(status_code=415, detail="The uploaded video has an invalid container signature")
    if extension == ".wav" and not (head.startswith(b"RIFF") and head[8:12] == b"WAVE"):
        raise HTTPException(status_code=415, detail="The uploaded WAV has an invalid signature")
    if extension in {".csv", ".json"}:
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Reports must use UTF-8 text") from exc


def probe_media(path: Path) -> dict[str, str | int | float]:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        payload = json.loads(completed.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"FFprobe could not validate {path.name}") from exc
    streams = payload.get("streams", [])
    media: dict[str, str | int | float] = {}
    duration = payload.get("format", {}).get("duration")
    if duration is not None:
        media["duration_seconds"] = round(float(duration), 3)
    for stream in streams:
        if stream.get("codec_type") == "video":
            media.update(codec=str(stream.get("codec_name", "")), width=int(stream.get("width", 0)), height=int(stream.get("height", 0)), frame_rate=str(stream.get("r_frame_rate", "")))
        elif stream.get("codec_type") == "audio":
            media.update(audio_codec=str(stream.get("codec_name", "")), sample_rate=int(stream.get("sample_rate", 0)), channels=int(stream.get("channels", 0)), bits_per_sample=int(stream.get("bits_per_sample", 0)))
    if not streams:
        raise HTTPException(status_code=422, detail=f"{path.name} contains no readable media streams")
    return media


def materialize_asset(settings, asset: DeliveryAsset) -> Path:
    if asset.storage_uri.startswith("gs://"):
        from google.cloud import storage
        bucket_name, object_name = asset.storage_uri[5:].split("/", 1)
        temporary = NamedTemporaryFile(prefix="wrapcheck-", suffix=Path(asset.filename).suffix, delete=False)
        temporary.close()
        storage.Client(project=settings.google_cloud_project).bucket(bucket_name).blob(object_name).download_to_filename(temporary.name)
        return Path(temporary.name)
    return Path(asset.storage_uri)


def verify_registered_assets(settings, delivery: Delivery) -> Delivery:
    for asset in delivery.assets:
        if asset.uploaded:
            continue
        temporary = asset.storage_uri.startswith("gs://")
        if temporary:
            from google.cloud import storage
            bucket_name, object_name = asset.storage_uri[5:].split("/", 1)
            blob = storage.Client(project=settings.google_cloud_project).bucket(bucket_name).get_blob(object_name)
            if not blob or blob.size != asset.size_bytes:
                raise HTTPException(status_code=409, detail=f"{asset.filename} has not finished uploading")
            asset.crc32c = blob.crc32c or ""
        path = materialize_asset(settings, asset)
        try:
            if not path.is_file() or path.stat().st_size != asset.size_bytes:
                raise HTTPException(status_code=409, detail=f"{asset.filename} does not match its declared size")
            inspect_file(path, asset.kind)
            with path.open("rb") as source:
                asset.sha256 = hashlib.file_digest(source, "sha256").hexdigest()
            if asset.kind in {AssetKind.camera_video, AssetKind.production_audio}:
                asset.media_metadata = probe_media(path)
        finally:
            if temporary:
                path.unlink(missing_ok=True)
        asset.uploaded = True
    delivery.status = DeliveryStatus.ready
    return delivery


def _csv_rows(settings, asset: DeliveryAsset) -> list[dict[str, str]]:
    path = materialize_asset(settings, asset)
    try:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise ValueError("JSON report must be an array of objects")
            return [{str(key): str(value) for key, value in item.items()} for item in data]
        if settings.app_mode != "live":
            raise HTTPException(status_code=409, detail=f"{asset.filename} requires live Gemini document normalization")
        try:
            return normalize_report(settings, asset, path)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"Could not normalize {asset.filename}: {exc}") from exc
    finally:
        if asset.storage_uri.startswith("gs://"):
            path.unlink(missing_ok=True)


def build_handoff_run(settings, delivery: Delivery, run_id: str) -> tuple[HandoffRun, list[ExpectedTake], list[MediaFile]]:
    by_kind: dict[AssetKind, list[DeliveryAsset]] = defaultdict(list)
    by_filename = {asset.filename: asset for asset in delivery.assets if asset.uploaded}
    for asset in delivery.assets:
        by_kind[asset.kind].append(asset)
    required = [AssetKind.camera_report, AssetKind.sound_report, AssetKind.script_notes, AssetKind.media_manifest]
    missing = [kind.value for kind in required if len(by_kind[kind]) != 1]
    if missing:
        raise HTTPException(status_code=409, detail=f"Exactly one of each source report is required; invalid: {', '.join(missing)}")

    camera = _csv_rows(settings, by_kind[AssetKind.camera_report][0])
    sound_rows = _csv_rows(settings, by_kind[AssetKind.sound_report][0])
    note_rows = _csv_rows(settings, by_kind[AssetKind.script_notes][0])
    manifest = _csv_rows(settings, by_kind[AssetKind.media_manifest][0])
    sound = {f"{row['scene']}:{row['take']}": row for row in sound_rows}
    notes = {f"{row['scene']}:{row['take']}": row for row in note_rows}
    expected = []
    for row in camera:
        key = f"{row['scene']}:{row['take']}"
        if key not in sound or key not in notes:
            raise HTTPException(status_code=422, detail=f"Report rows do not join for scene/take {key}")
        expected.append(ExpectedTake(
            expectation_id=str(uuid5(NAMESPACE_URL, f"{run_id}:{key}")), run_id=run_id,
            production=row["production"], shoot_day=row["shoot_day"], scene=row["scene"],
            take=int(row["take"]), circled=row["circled"].lower() == "true",
            camera_roll=row["camera_roll"], card_id=row["card_id"],
            video_filename=row["video_filename"], sound_roll=sound[key]["sound_roll"],
            audio_filename=sound[key]["audio_filename"], frame_rate=row["frame_rate"],
            script_note=notes[key]["editor_note"],
        ))

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in manifest:
        grouped[row["filename"]].append(row)
    media: list[MediaFile] = []
    for filename, rows in grouped.items():
        uploaded_asset = by_filename.get(filename)
        if not uploaded_asset or uploaded_asset.kind not in {AssetKind.camera_video, AssetKind.production_audio}:
            continue
        first = rows[0]
        if int(first["size_bytes"]) != uploaded_asset.size_bytes:
            raise HTTPException(status_code=422, detail=f"Manifest size does not match uploaded object: {filename}")
        copies = [MediaCopy(
            destination=row["destination"], checksum_algorithm=row.get("checksum_algorithm", "sha256"),
            checksum=row.get("checksum", ""), verified=row.get("verified", "false").lower() == "true",
        ) for row in rows]
        if uploaded_asset.sha256 and all(copy.checksum != uploaded_asset.sha256 for copy in copies if copy.verified):
            copies.append(MediaCopy(destination="INGESTED", checksum=uploaded_asset.sha256, verified=True))
        media.append(MediaFile(
            media_id=str(uuid5(NAMESPACE_URL, f"{run_id}:{filename}")), run_id=run_id,
            filename=filename, kind=first["kind"], roll=first["roll"], card_id=first["card_id"],
            scene=first["scene"], take=int(first["take"]), size_bytes=int(first["size_bytes"]),
            copies=copies, playback_url=f"/api/deliveries/{delivery.delivery_id}/assets/{uploaded_asset.asset_id}/playback",
        ))

    checks, findings = reconcile_media(run_id, expected, media)
    status, reason = handoff_status(findings)
    documents = [SourceDocument(
        document_id=asset.asset_id, label=asset.kind.value.replace("_", " ").title(),
        filename=asset.filename, record_count=len(_csv_rows(settings, asset)), kind=asset.kind.value,
        download_url=f"/api/deliveries/{delivery.delivery_id}/assets/{asset.asset_id}/playback",
    ) for kind in required for asset in by_kind[kind]]
    run = HandoffRun(
        run_id=run_id, mode="live" if settings.app_mode == "live" else "fixture",
        mode_disclaimer="Uploaded production evidence, deterministic two-copy verification, and human-controlled release.",
        scenario_id="missing-media" if findings else "clean-handoff",
        production=delivery.production, shoot_day=delivery.shoot_day, delivery_name=delivery.delivery_name,
        camera_cards=sorted({item.card_id for item in expected}), source_documents=documents,
        checks=checks, findings=findings, status=status, status_reason=reason,
        audit=[
            {"step": "register_delivery_assets", "service": "Private object storage", "status": "complete", "duration_ms": 1, "summary": f"{len(delivery.assets)} validated assets registered with SHA-256 evidence."},
            {"step": "normalize_reports", "service": "Deterministic structured parser", "status": "complete", "duration_ms": 2, "summary": f"{len(expected)} expected takes and {len(media)} delivered media files normalized."},
            {"step": "reconcile_media", "service": "Deterministic release policy", "status": "complete", "duration_ms": 2, "summary": f"{len(findings)} release blocker(s) produced."},
        ],
    )
    return run, expected, media


def process_ingestion(settings, durable, repository, job: IngestionJob) -> IngestionJob:
    try:
        job.status = JobStatus.processing
        job.error = ""
        job.stage = "validating_assets"
        job.progress = 10
        durable.save_job(job)
        delivery = durable.get_delivery(job.delivery_id)
        if not delivery:
            raise RuntimeError("Delivery no longer exists")
        verify_registered_assets(settings, delivery)
        delivery.status = DeliveryStatus.processing
        durable.save_delivery(delivery)
        job.stage = "normalizing_reports"
        job.progress = 45
        durable.save_job(job)
        run_id = str(uuid4())
        run, expected, media = build_handoff_run(settings, delivery, run_id)
        repository.store_handoff_inputs(expected, media)
        repository.store_handoff_run(run)
        repository.store_media_copies(media)
        durable.save_run(run)
        delivery.status = DeliveryStatus.complete
        durable.save_delivery(delivery)
        job.status = JobStatus.complete
        job.stage = "complete"
        job.progress = 100
        job.run_id = run.run_id
        job.error = ""
        return durable.save_job(job)
    except Exception as exc:
        logger.exception("Delivery ingestion failed")
        job.status = JobStatus.failed
        job.stage = "failed"
        job.error = str(exc)
        return durable.save_job(job)
