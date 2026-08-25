from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ReviewDecision(StrEnum):
    confirmed_error = "confirmed_error"
    intentional_change = "intentional_change"
    needs_review = "needs_review"


class Observation(BaseModel):
    observation_id: str
    production_id: str
    scene_id: str
    shot_id: str
    take_id: str
    timestamp_start_ms: int = Field(ge=0)
    timestamp_end_ms: int = Field(ge=0)
    entity_type: str
    entity_name: str
    attribute: str
    observed_value: str
    confidence: float = Field(ge=0, le=1)
    evidence_description: str
    evidence_frame_timestamp_ms: int = Field(ge=0)
    source: Literal["gemini", "fixture", "human"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GeminiObservationBatch(BaseModel):
    observations: list[Observation]


class Conflict(BaseModel):
    conflict_id: str
    production_id: str
    scene_id: str
    reference_observation_id: str
    current_observation_id: str
    entity_type: str
    entity_name: str
    attribute: str
    reference_value: str
    current_value: str
    reference_evidence: str
    current_evidence: str
    reference_timestamp_ms: int
    current_timestamp_ms: int
    confidence: float
    severity: Literal["blocking", "review"]
    deterministic_reason: str
    decision: ReviewDecision | None = None


class WorkflowStep(BaseModel):
    name: str
    status: Literal["complete", "waiting", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    input_summary: str
    output_summary: str
    tool_name: str
    error: str | None = None


class Production(BaseModel):
    production_id: str
    title: str
    scene_id: str
    scene_heading: str
    script_excerpt: str


class Take(BaseModel):
    take_id: str
    label: str
    role: Literal["reference", "current"]
    filename: str
    duration_ms: int


class ReviewSnapshot(BaseModel):
    mode: Literal["demo", "live"]
    mode_disclaimer: str
    production: Production
    takes: list[Take]
    observations: list[Observation]
    conflicts: list[Conflict]
    workflow: list[WorkflowStep]
    recommendation: Literal["safe_to_wrap", "do_not_wrap", "needs_review"]
    recommendation_reason: str


class DecisionRequest(BaseModel):
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class LiveRunRequest(BaseModel):
    production_id: str
    scene_id: str
    reference_take_id: str
    current_take_id: str
    reference_gcs_uri: str
    current_gcs_uri: str


# WrapCheck 2.0 release-gate contracts. Legacy review models remain above so
# existing clients can migrate without an all-at-once deployment.
class RequirementType(StrEnum):
    continuity = "continuity"
    dialogue = "dialogue"


class ObservationResult(StrEnum):
    observed = "observed"
    not_observed = "not_observed"
    uncertain = "uncertain"


class FindingType(StrEnum):
    mismatch = "mismatch"
    missing_required_beat = "missing_required_beat"
    uncertain = "uncertain"


class FindingDecision(StrEnum):
    pickup = "pickup"
    intentional_change = "intentional_change"
    needs_review = "needs_review"


class GateStatus(StrEnum):
    hold_setup = "hold_setup"
    needs_supervisor_review = "needs_supervisor_review"
    ready_for_supervisor_signoff = "ready_for_supervisor_signoff"
    cleared_by_supervisor = "cleared_by_supervisor"


class SceneRequirement(BaseModel):
    requirement_id: str
    requirement_type: RequirementType
    label: str
    entity_name: str
    attribute: str
    expected_value: str | None = None


class SceneBrief(BaseModel):
    production_id: str = Field(min_length=1, max_length=120)
    production_title: str = Field(min_length=1, max_length=160)
    scene_id: str = Field(min_length=1, max_length=120)
    scene_heading: str = Field(min_length=1, max_length=200)
    setup_id: str = Field(min_length=1, max_length=120)
    required_dialogue: str = Field(min_length=1, max_length=500)
    requirements: list[SceneRequirement]


class RequirementObservation(BaseModel):
    observation_id: str
    run_id: str
    production_id: str
    scene_id: str
    setup_id: str
    take_id: str
    requirement_id: str
    result: ObservationResult
    normalized_value: str
    confidence: float = Field(ge=0, le=1)
    evidence_description: str
    timestamp_start_ms: int | None = Field(default=None, ge=0)
    timestamp_end_ms: int | None = Field(default=None, ge=0)
    source: Literal["gemini", "fixture"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RequirementObservationBatch(BaseModel):
    observations: list[RequirementObservation]


class CuratedAsset(BaseModel):
    asset_id: str
    take_id: str
    label: str
    role: Literal["reference", "candidate"]
    duration_ms: int = Field(gt=0)
    playback_url: str
    poster_variant: Literal["reference", "clean", "flawed"]


class WrapFinding(BaseModel):
    finding_id: str
    run_id: str
    requirement_id: str
    finding_type: FindingType
    requirement_type: RequirementType
    label: str
    expected_value: str
    observed_value: str
    reference_evidence: str
    candidate_evidence: str
    reference_timestamp_ms: int | None = None
    candidate_timestamp_ms: int | None = None
    inspected_start_ms: int = 0
    inspected_end_ms: int = 0
    confidence: float = Field(ge=0, le=1)
    severity: Literal["blocking", "review"]
    recommended_action: str
    decision: FindingDecision | None = None
    reviewer_note: str = ""


class AuditEvent(BaseModel):
    step: str
    service: str
    status: Literal["complete", "failed", "skipped"]
    duration_ms: int = Field(ge=0)
    summary: str
    query: str | None = None


class WrapRun(BaseModel):
    run_id: str
    mode: Literal["fixture", "live"]
    mode_disclaimer: str
    brief: SceneBrief
    reference_asset: CuratedAsset
    candidate_asset: CuratedAsset
    findings: list[WrapFinding]
    status: GateStatus
    status_reason: str
    pickup_count: int
    cleared_by: str | None = None
    cleared_at: datetime | None = None
    audit: list[AuditEvent]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DemoRunRequest(BaseModel):
    candidate_asset_id: Literal["candidate-clean", "candidate-flawed"] = "candidate-flawed"
    production_title: str = Field(default="The Last Signal", min_length=1, max_length=160)
    scene_heading: str = Field(default="INT. KITCHEN — NIGHT", min_length=1, max_length=200)
    setup_id: str = Field(default="Setup 24B-A", min_length=1, max_length=120)
    required_dialogue: str = Field(default="The drive leaves at six.", min_length=1, max_length=500)


class FindingDecisionRequest(BaseModel):
    decision: FindingDecision
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class ClearanceRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
