from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from .models import AuditEvent


class ChecksumState(StrEnum):
    verified = "verified"
    pending = "pending"
    failed = "failed"


class HandoffIssueType(StrEnum):
    missing_video = "missing_video"
    missing_audio = "missing_audio"
    checksum_pending = "checksum_pending"
    checksum_mismatch = "checksum_mismatch"
    metadata_mismatch = "metadata_mismatch"
    duplicate_media = "duplicate_media"


class HandoffDecision(StrEnum):
    recovered = "recovered"
    approved_exception = "approved_exception"
    needs_review = "needs_review"


class HandoffStatus(StrEnum):
    hold_media = "hold_media"
    needs_review = "needs_review"
    ready_for_release = "ready_for_release"
    released_by_dit = "released_by_dit"


class SourceDocument(BaseModel):
    document_id: str
    label: str
    filename: str
    record_count: int
    kind: Literal["camera_report", "sound_report", "script_notes", "media_manifest"]
    download_url: str


class ExpectedTake(BaseModel):
    expectation_id: str
    run_id: str
    production: str
    shoot_day: str
    scene: str
    take: int = Field(gt=0)
    circled: bool
    camera_roll: str
    card_id: str
    video_filename: str
    sound_roll: str
    audio_filename: str
    frame_rate: str
    script_note: str


class MediaCopy(BaseModel):
    destination: str = Field(min_length=1, max_length=80)
    checksum_algorithm: Literal["sha256", "crc32c"] = "sha256"
    checksum: str = ""
    verified: bool = False
    verified_at: datetime | None = None


class MediaFile(BaseModel):
    media_id: str
    run_id: str
    filename: str
    kind: Literal["video", "audio"]
    roll: str
    card_id: str
    scene: str
    take: int = Field(gt=0)
    size_bytes: int = Field(ge=0)
    copies: list[MediaCopy] = Field(default_factory=list)
    playback_url: str | None = None

    @property
    def verified_copies(self) -> list[MediaCopy]:
        return [copy for copy in self.copies if copy.verified and copy.checksum]

    @property
    def checksum_consistent(self) -> bool:
        checksums = {copy.checksum for copy in self.verified_copies}
        return len(checksums) <= 1

    @property
    def checksum_state(self) -> ChecksumState:
        if not self.checksum_consistent:
            return ChecksumState.failed
        destinations = {copy.destination for copy in self.verified_copies}
        return ChecksumState.verified if len(destinations) >= 2 else ChecksumState.pending


class TakeCheck(BaseModel):
    scene_take: str
    circled: bool
    camera_roll: str
    sound_roll: str
    video_filename: str
    audio_filename: str
    video_state: Literal["present", "missing"]
    audio_state: Literal["present", "missing"]
    checksum_state: ChecksumState
    verified_video_copies: int = 0
    verified_audio_copies: int = 0
    video_playback_url: str | None = None
    audio_playback_url: str | None = None
    script_note: str


class HandoffFinding(BaseModel):
    finding_id: str
    run_id: str
    issue_type: HandoffIssueType
    severity: Literal["blocking", "review"]
    title: str
    scene_take: str
    card_id: str
    expected: str
    observed: str
    evidence: list[str]
    required_action: str
    decision: HandoffDecision | None = None
    reviewer_note: str = ""


class HandoffRun(BaseModel):
    run_id: str
    mode: Literal["fixture", "live"]
    mode_disclaimer: str
    scenario_id: Literal["missing-media", "clean-handoff"]
    production: str
    shoot_day: str
    delivery_name: str
    camera_cards: list[str]
    source_documents: list[SourceDocument]
    checks: list[TakeCheck]
    findings: list[HandoffFinding]
    status: HandoffStatus
    status_reason: str
    released_by: str | None = None
    released_at: datetime | None = None
    audit: list[AuditEvent]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HandoffRunRequest(BaseModel):
    scenario_id: Literal["missing-media", "clean-handoff"] = "missing-media"
    production: str = Field(default="The Last Signal", min_length=1, max_length=160)
    shoot_day: str = Field(default="Day 12 · 25 Aug 2026", min_length=1, max_length=120)
    delivery_name: str = Field(default="Editorial shuttle 12A", min_length=1, max_length=160)


class HandoffDecisionRequest(BaseModel):
    decision: HandoffDecision
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class HandoffReleaseRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
