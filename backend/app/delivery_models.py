from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def utc_now():
    return datetime.now(timezone.utc)


class AssetKind(StrEnum):
    camera_report = "camera_report"
    sound_report = "sound_report"
    script_notes = "script_notes"
    media_manifest = "media_manifest"
    camera_video = "camera_video"
    production_audio = "production_audio"


class DeliveryStatus(StrEnum):
    draft = "draft"
    uploading = "uploading"
    ready = "ready"
    processing = "processing"
    complete = "complete"
    failed = "failed"


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    complete = "complete"
    failed = "failed"


class DeliveryCreateRequest(BaseModel):
    production: str = Field(min_length=1, max_length=160)
    shoot_day: str = Field(min_length=1, max_length=120)
    delivery_name: str = Field(min_length=1, max_length=160)


class DeliveryAsset(BaseModel):
    asset_id: str
    delivery_id: str
    kind: AssetKind
    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    storage_uri: str
    crc32c: str = ""
    sha256: str = ""
    uploaded: bool = False
    media_metadata: dict[str, str | int | float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Delivery(BaseModel):
    delivery_id: str
    production: str
    shoot_day: str
    delivery_name: str
    status: DeliveryStatus = DeliveryStatus.draft
    assets: list[DeliveryAsset] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UploadAssetDeclaration(BaseModel):
    kind: AssetKind
    filename: str = Field(min_length=1, max_length=160)
    content_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(gt=0)


class UploadTargetsRequest(BaseModel):
    assets: list[UploadAssetDeclaration] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def total_limit(self):
        if sum(item.size_bytes for item in self.assets) > 1024 * 1024 * 1024:
            raise ValueError("A delivery may not exceed 1 GB")
        return self


class UploadTarget(BaseModel):
    asset: DeliveryAsset
    method: Literal["PUT"] = "PUT"
    upload_url: str
    expires_in_seconds: int = 900
    required_headers: dict[str, str]


class UploadTargetsResponse(BaseModel):
    delivery_id: str
    targets: list[UploadTarget]


class IngestionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class IngestionJob(BaseModel):
    job_id: str
    delivery_id: str
    idempotency_key: str
    status: JobStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    run_id: str | None = None
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False
    request_id: str


class ApiError(BaseModel):
    error: ApiErrorDetail
