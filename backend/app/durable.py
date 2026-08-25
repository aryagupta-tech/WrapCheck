import json
from datetime import datetime, timezone
from threading import Lock

from .delivery_models import Delivery, IngestionJob
from .handoff_models import HandoffRun


def _now():
    return datetime.now(timezone.utc)


class DurableStore:
    """ClickHouse-backed snapshots with a process cache only as a local outage fallback."""

    def __init__(self, repository):
        self.repository = repository
        self._lock = Lock()
        self._deliveries: dict[str, Delivery] = {}
        self._jobs: dict[str, IngestionJob] = {}
        self._runs: dict[str, HandoffRun] = {}

    @property
    def client(self):
        return self.repository.client

    def save_delivery(self, delivery: Delivery) -> Delivery:
        delivery.updated_at = _now()
        with self._lock:
            self._deliveries[delivery.delivery_id] = delivery.model_copy(deep=True)
        self.client.insert(
            "delivery_snapshots",
            [[delivery.delivery_id, delivery.model_dump_json(), delivery.status.value, delivery.updated_at]],
            column_names=["delivery_id", "payload_json", "status", "updated_at"],
        )
        for asset in delivery.assets:
            self.client.insert(
                "delivery_assets",
                [[
                    asset.asset_id, asset.delivery_id, asset.kind.value, asset.filename,
                    asset.content_type, asset.size_bytes, asset.storage_uri, asset.crc32c,
                    asset.sha256, json.dumps(asset.media_metadata, separators=(",", ":")), asset.uploaded, asset.created_at, delivery.updated_at,
                ]],
                column_names=[
                    "asset_id", "delivery_id", "kind", "filename", "content_type",
                    "size_bytes", "storage_uri", "crc32c", "sha256", "metadata_json", "uploaded",
                    "created_at", "updated_at",
                ],
            )
        return delivery

    def get_delivery(self, delivery_id: str) -> Delivery | None:
        try:
            result = self.client.query(
                "SELECT argMax(payload_json, updated_at) FROM delivery_snapshots "
                "WHERE delivery_id = {delivery_id:String}",
                parameters={"delivery_id": delivery_id},
            )
            if result.first_row and result.first_row[0]:
                delivery = Delivery.model_validate_json(result.first_row[0])
                with self._lock:
                    self._deliveries[delivery_id] = delivery.model_copy(deep=True)
                return delivery
        except Exception:
            pass
        cached = self._deliveries.get(delivery_id)
        return cached.model_copy(deep=True) if cached else None

    def save_job(self, job: IngestionJob) -> IngestionJob:
        job.updated_at = _now()
        with self._lock:
            self._jobs[job.job_id] = job.model_copy(deep=True)
        self.client.insert(
            "ingestion_job_snapshots",
            [[job.job_id, job.delivery_id, job.idempotency_key, job.model_dump_json(), job.status.value, job.updated_at]],
            column_names=["job_id", "delivery_id", "idempotency_key", "payload_json", "status", "updated_at"],
        )
        return job

    def get_job(self, job_id: str) -> IngestionJob | None:
        try:
            result = self.client.query(
                "SELECT argMax(payload_json, updated_at) FROM ingestion_job_snapshots "
                "WHERE job_id = {job_id:String}",
                parameters={"job_id": job_id},
            )
            if result.first_row and result.first_row[0]:
                return IngestionJob.model_validate_json(result.first_row[0])
        except Exception:
            pass
        cached = self._jobs.get(job_id)
        return cached.model_copy(deep=True) if cached else None

    def find_job(self, delivery_id: str, idempotency_key: str) -> IngestionJob | None:
        try:
            result = self.client.query(
                "SELECT argMax(payload_json, updated_at) FROM ingestion_job_snapshots "
                "WHERE delivery_id = {delivery_id:String} AND idempotency_key = {key:String}",
                parameters={"delivery_id": delivery_id, "key": idempotency_key},
            )
            if result.first_row and result.first_row[0]:
                return IngestionJob.model_validate_json(result.first_row[0])
        except Exception:
            pass
        return next((job.model_copy(deep=True) for job in self._jobs.values() if job.delivery_id == delivery_id and job.idempotency_key == idempotency_key), None)

    def save_run(self, run: HandoffRun) -> HandoffRun:
        updated_at = _now()
        with self._lock:
            self._runs[run.run_id] = run.model_copy(deep=True)
        self.client.insert(
            "handoff_run_snapshots",
            [[run.run_id, run.model_dump_json(), run.status.value, updated_at]],
            column_names=["run_id", "payload_json", "status", "updated_at"],
        )
        return run

    def get_run(self, run_id: str) -> HandoffRun | None:
        try:
            result = self.client.query(
                "SELECT argMax(payload_json, updated_at) FROM handoff_run_snapshots "
                "WHERE run_id = {run_id:String}",
                parameters={"run_id": run_id},
            )
            if result.first_row and result.first_row[0]:
                run = HandoffRun.model_validate_json(result.first_row[0])
                with self._lock:
                    self._runs[run_id] = run.model_copy(deep=True)
                return run
        except Exception:
            pass
        cached = self._runs.get(run_id)
        return cached.model_copy(deep=True) if cached else None

    def find_run_by_finding(self, finding_id: str) -> HandoffRun | None:
        try:
            result = self.client.query(
                "SELECT argMax(run_id, created_at) FROM handoff_findings "
                "WHERE finding_id = {finding_id:String}",
                parameters={"finding_id": finding_id},
            )
            if result.first_row and result.first_row[0]:
                return self.get_run(result.first_row[0])
        except Exception:
            pass
        return next((run.model_copy(deep=True) for run in self._runs.values() if any(item.finding_id == finding_id for item in run.findings)), None)
