import csv
from collections import defaultdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .handoff_gate import handoff_status, reconcile_media
from .handoff_models import (
    ExpectedTake, HandoffRun, HandoffRunRequest, MediaCopy, MediaFile, SourceDocument,
)


DATA_ROOT = Path(__file__).with_name("demo_data")


def _rows(filename: str):
    with (DATA_ROOT / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_handoff_inputs(run_id: str, scenario_id: str):
    camera = _rows("camera_report.csv")
    sound_rows = _rows("sound_report.csv")
    note_rows = _rows("script_notes.csv")
    sound = {f"{row['scene']}:{row['take']}": row for row in sound_rows}
    notes = {f"{row['scene']}:{row['take']}": row for row in note_rows}
    expected = []
    for row in camera:
        key = f"{row['scene']}:{row['take']}"
        expected.append(ExpectedTake(
            expectation_id=str(uuid5(NAMESPACE_URL, f"{run_id}:{key}")),
            run_id=run_id,
            production=row["production"],
            shoot_day=row["shoot_day"],
            scene=row["scene"],
            take=int(row["take"]),
            circled=row["circled"].lower() == "true",
            camera_roll=row["camera_roll"],
            card_id=row["card_id"],
            video_filename=row["video_filename"],
            sound_roll=sound[key]["sound_roll"],
            audio_filename=sound[key]["audio_filename"],
            frame_rate=row["frame_rate"],
            script_note=notes[key]["editor_note"],
        ))

    manifest_name = "manifest_problem.csv" if scenario_id == "missing-media" else "manifest_clean.csv"
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows(manifest_name):
        grouped[row["filename"]].append(row)

    media = []
    for filename, rows in grouped.items():
        first = rows[0]
        copies = [MediaCopy(
            destination=row["destination"],
            checksum_algorithm=row.get("checksum_algorithm", "sha256"),
            checksum=row.get("checksum", ""),
            verified=row.get("verified", "false").lower() == "true",
        ) for row in rows]
        media.append(MediaFile(
            media_id=str(uuid5(NAMESPACE_URL, f"{run_id}:{filename}")),
            run_id=run_id,
            filename=filename,
            kind=first["kind"],
            roll=first["roll"],
            card_id=first["card_id"],
            scene=first["scene"],
            take=int(first["take"]),
            size_bytes=int(first["size_bytes"]),
            copies=copies,
            playback_url=f"/api/demo-assets/{filename}",
        ))

    documents = [
        SourceDocument(document_id="camera", label="Camera report · A camera", filename="camera_report.csv", record_count=len(camera), kind="camera_report", download_url="/api/handoff/demo-files/camera_report.csv"),
        SourceDocument(document_id="sound", label="Sound report · SR12", filename="sound_report.csv", record_count=len(sound_rows), kind="sound_report", download_url="/api/handoff/demo-files/sound_report.csv"),
        SourceDocument(document_id="script", label="Script supervisor notes", filename="script_notes.csv", record_count=len(note_rows), kind="script_notes", download_url="/api/handoff/demo-files/script_notes.csv"),
        SourceDocument(document_id="manifest", label="Two-destination offload manifest", filename=manifest_name, record_count=sum(len(rows) for rows in grouped.values()), kind="media_manifest", download_url=f"/api/handoff/demo-files/{manifest_name}"),
    ]
    return expected, media, documents


def fixture_handoff_run(request: HandoffRunRequest):
    run_id = str(uuid4())
    expected, media, documents = load_handoff_inputs(run_id, request.scenario_id)
    checks, findings = reconcile_media(run_id, expected, media)
    status, reason = handoff_status(findings)
    run = HandoffRun(
        run_id=run_id,
        mode="fixture",
        mode_disclaimer="Original camera and sound assets with deterministic two-copy reconciliation. No Gemini or MCP call is claimed in fixture mode.",
        scenario_id=request.scenario_id,
        production=request.production,
        shoot_day=request.shoot_day,
        delivery_name=request.delivery_name,
        camera_cards=sorted({item.card_id for item in expected}),
        source_documents=documents,
        checks=checks,
        findings=findings,
        status=status,
        status_reason=reason,
        audit=[
            {"step": "register_delivery_assets", "service": "Curated original media", "status": "complete", "duration_ms": 3, "summary": f"{len(media)} unique media files and two-destination copy records registered."},
            {"step": "retrieve_delivery_context", "service": "Not invoked in fixture mode", "status": "skipped", "duration_ms": 0, "summary": "Live mode retrieves the same normalized records through mcp-clickhouse."},
            {"step": "reconcile_media", "service": "Deterministic release policy", "status": "complete", "duration_ms": 2, "summary": f"{len(media)} delivered files checked against {len(expected)} expected takes."},
        ],
    )
    return run, expected, media
