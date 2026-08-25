import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from .delivery_models import (
    Delivery, DeliveryCreateRequest, DeliveryStatus, IngestionJob, IngestionRequest,
    JobStatus, UploadTargetsRequest, UploadTargetsResponse,
)
from .delivery_service import create_upload_target, process_ingestion, store_local_upload
from .services.session import signed_session_hash


def create_delivery_router(settings, durable, repository) -> APIRouter:
    router = APIRouter()

    @router.post("/api/deliveries", response_model=Delivery, status_code=201)
    def create_delivery(payload: DeliveryCreateRequest, request: Request, response: Response):
        session_hash = ""
        if settings.app_mode == "live":
            session_hash = signed_session_hash(settings, request, response)
            try:
                session_count, global_count = repository.public_events_in_window(session_hash, "delivery_create")
                if session_count >= settings.upload_deliveries_per_10_minutes or global_count >= settings.global_runs_per_10_minutes:
                    raise HTTPException(status_code=429, detail="Public upload quota reached. Try again in ten minutes.")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Upload quota service is unavailable") from exc
        delivery = Delivery(
            delivery_id=str(uuid4()),
            production=payload.production,
            shoot_day=payload.shoot_day,
            delivery_name=payload.delivery_name,
        )
        saved = durable.save_delivery(delivery)
        if settings.app_mode == "live":
            repository.record_public_event(session_hash, "delivery_create", delivery.delivery_id)
        return saved

    @router.get("/api/deliveries/{delivery_id}", response_model=Delivery)
    def get_delivery(delivery_id: str):
        delivery = durable.get_delivery(delivery_id)
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        return delivery

    @router.post("/api/deliveries/{delivery_id}/upload-targets", response_model=UploadTargetsResponse)
    def create_upload_targets(delivery_id: str, payload: UploadTargetsRequest):
        delivery = durable.get_delivery(delivery_id)
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        if delivery.status not in {DeliveryStatus.draft, DeliveryStatus.uploading}:
            raise HTTPException(status_code=409, detail="This delivery no longer accepts uploads")
        if len(delivery.assets) + len(payload.assets) > 20:
            raise HTTPException(status_code=413, detail="A delivery may contain at most 20 assets")
        if sum(asset.size_bytes for asset in delivery.assets) + sum(asset.size_bytes for asset in payload.assets) > 1024 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="A delivery may not exceed 1 GB")
        existing_names = {asset.filename.casefold() for asset in delivery.assets}
        targets = []
        for declaration in payload.assets:
            if declaration.filename.casefold() in existing_names:
                raise HTTPException(status_code=409, detail=f"Duplicate filename: {declaration.filename}")
            target = create_upload_target(settings, delivery, declaration)
            targets.append(target)
            delivery.assets.append(target.asset)
            existing_names.add(target.asset.filename.casefold())
        delivery.status = DeliveryStatus.uploading
        durable.save_delivery(delivery)
        return UploadTargetsResponse(delivery_id=delivery_id, targets=targets)

    @router.put("/api/deliveries/{delivery_id}/assets/{asset_id}/content", response_model=Delivery)
    async def upload_local_content(delivery_id: str, asset_id: str, request: Request):
        if settings.app_mode == "live":
            raise HTTPException(status_code=404, detail="Live uploads use signed private-storage URLs")
        delivery = durable.get_delivery(delivery_id)
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        asset = next((item for item in delivery.assets if item.asset_id == asset_id), None)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        if asset.uploaded:
            raise HTTPException(status_code=409, detail="Asset content is immutable after upload")
        await store_local_upload(request, asset)
        durable.save_delivery(delivery)
        return delivery

    @router.post("/api/deliveries/{delivery_id}/ingestions", response_model=IngestionJob, status_code=202)
    def create_ingestion(delivery_id: str, payload: IngestionRequest, background_tasks: BackgroundTasks):
        delivery = durable.get_delivery(delivery_id)
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        existing = durable.find_job(delivery_id, payload.idempotency_key)
        if existing:
            return existing
        job = IngestionJob(
            job_id=str(uuid4()), delivery_id=delivery_id, idempotency_key=payload.idempotency_key,
            status=JobStatus.queued, stage="queued", progress=0,
        )
        durable.save_job(job)
        if settings.app_mode == "live" and getattr(settings, "cloud_tasks_queue", None):
            _enqueue_cloud_task(settings, job)
        else:
            background_tasks.add_task(process_ingestion, settings, durable, repository, job)
        return job

    @router.get("/api/ingestions/{job_id}", response_model=IngestionJob)
    def get_ingestion(job_id: str):
        job = durable.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Ingestion job not found")
        return job

    @router.post("/internal/ingestions/{job_id}/process", response_model=IngestionJob, include_in_schema=False)
    def process_task(job_id: str, x_wrapcheck_task_secret: str = Header(default="")):
        if x_wrapcheck_task_secret != settings.demo_quota_secret:
            raise HTTPException(status_code=403, detail="Invalid task credential")
        job = durable.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Ingestion job not found")
        if job.status == JobStatus.complete:
            return job
        return process_ingestion(settings, durable, repository, job)

    @router.get("/api/deliveries/{delivery_id}/assets/{asset_id}/playback")
    def playback_delivery_asset(delivery_id: str, asset_id: str):
        delivery = durable.get_delivery(delivery_id)
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")
        asset = next((item for item in delivery.assets if item.asset_id == asset_id), None)
        if not asset or not asset.uploaded:
            raise HTTPException(status_code=404, detail="Asset not available")
        if asset.storage_uri.startswith("gs://"):
            from google.cloud import storage
            bucket_name, object_name = asset.storage_uri[5:].split("/", 1)
            blob = storage.Client(project=settings.google_cloud_project).bucket(bucket_name).blob(object_name)
            return RedirectResponse(blob.generate_signed_url(version="v4", expiration=timedelta(minutes=15), method="GET"))
        path = Path(asset.storage_uri)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stored asset no longer exists")
        return FileResponse(path, media_type=asset.content_type, filename=asset.filename)

    @router.get("/api/demo-packages/{variant}")
    def download_demo_package(variant: str):
        names = {"problem": "problem-delivery.zip", "recovered": "recovered-delivery.zip"}
        if variant not in names:
            raise HTTPException(status_code=404, detail="Demo package not found")
        path = Path(__file__).with_name("demo_packages") / names[variant]
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Demo package has not been generated")
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @router.get("/api/demo-assets/{filename}")
    def playback_demo_asset(filename: str):
        safe_name = Path(filename).name
        if safe_name != filename:
            raise HTTPException(status_code=404, detail="Asset not found")
        path = Path(__file__).with_name("demo_assets") / safe_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        media_type = "video/mp4" if path.suffix.lower() == ".mp4" else "audio/wav"
        return FileResponse(path, media_type=media_type, filename=path.name)

    return router


def _enqueue_cloud_task(settings, job: IngestionJob) -> None:
    from google.cloud import tasks_v2
    client = tasks_v2.CloudTasksClient()
    parent = settings.cloud_tasks_queue if settings.cloud_tasks_queue.startswith("projects/") else client.queue_path(settings.google_cloud_project, settings.google_cloud_location, settings.cloud_tasks_queue)
    target = f"{settings.cloud_run_backend_url.rstrip('/')}/internal/ingestions/{job.job_id}/process"
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": target,
            "headers": {"Content-Type": "application/json", "X-WrapCheck-Task-Secret": settings.demo_quota_secret},
            "body": json.dumps({"job_id": job.job_id}).encode(),
            "oidc_token": {"service_account_email": settings.cloud_tasks_service_account},
        }
    }
    client.create_task(parent=parent, task=task)
