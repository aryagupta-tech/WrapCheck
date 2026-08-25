from datetime import datetime, timezone, timedelta

from .models import (
    AuditEvent, CuratedAsset, DemoRunRequest, Observation, ObservationResult,
    Production, RequirementObservation, RequirementType, SceneBrief,
    SceneRequirement, Take, WorkflowStep, WrapRun,
)
from .gate import evaluate_requirements, gate_status
from uuid import uuid4

PRODUCTION = Production(
    production_id="prod-night-window",
    title="The Last Signal",
    scene_id="scene-24b",
    scene_heading="INT. SIGNAL ROOM — NIGHT",
    script_excerpt='MARA checks her watch, lifts the half-full glass, and says, "We have one minute."',
)

TAKES = [
    Take(take_id="take-3", label="Take 3 · Circle take", role="reference", filename="signal-room-t03.mp4", duration_ms=42000),
    Take(take_id="take-7", label="Take 7 · Current", role="current", filename="signal-room-t07.mp4", duration_ms=42000),
]

_NOW = datetime(2026, 8, 19, 14, 32, tzinfo=timezone.utc)


def _obs(identifier: str, take: str, entity_type: str, entity: str, attribute: str, value: str, confidence: float, evidence: str, timestamp: int) -> Observation:
    return Observation(
        observation_id=identifier,
        production_id=PRODUCTION.production_id,
        scene_id=PRODUCTION.scene_id,
        shot_id="24B-A",
        take_id=take,
        timestamp_start_ms=max(0, timestamp - 600),
        timestamp_end_ms=timestamp + 600,
        entity_type=entity_type,
        entity_name=entity,
        attribute=attribute,
        observed_value=value,
        confidence=confidence,
        evidence_description=evidence,
        evidence_frame_timestamp_ms=timestamp,
        source="fixture",
        created_at=_NOW,
    )


REFERENCE_OBSERVATIONS = [
    _obs("ref-watch", "take-3", "wardrobe", "Mara's watch", "wrist", "left", .98, "Watch is visible above Mara's left cuff.", 8100),
    _obs("ref-glass", "take-3", "prop", "drinking glass", "fill_level", "half-full", .96, "Liquid line sits at the midpoint of the glass.", 14200),
    _obs("ref-folder", "take-3", "prop", "red folder", "position", "right of console", .94, "Folder rests to the right of the radio console.", 19100),
    _obs("ref-jacket", "take-3", "wardrobe", "Mara's jacket", "state", "buttoned", .97, "Top and middle jacket buttons are fastened.", 5300),
    _obs("ref-dialogue", "take-3", "dialogue", "Mara line 18", "text", "We have one minute", .99, "Mara audibly delivers the scripted line.", 28600),
    _obs("ref-phone", "take-3", "prop", "desk phone", "presence", "present", .95, "Black phone is visible at frame left.", 22100),
    _obs("ref-clock", "take-3", "prop", "wall clock", "display", "unknown", .42, "Clock face is too soft to read.", 32000),
]

CURRENT_OBSERVATIONS = [
    _obs("cur-watch", "take-7", "wardrobe", "Mara's watch", "wrist", "right", .97, "Watch is clearly visible on Mara's right wrist.", 8300),
    _obs("cur-glass", "take-7", "prop", "drinking glass", "fill_level", "nearly empty", .95, "Only a shallow layer of liquid remains.", 14400),
    _obs("cur-folder", "take-7", "prop", "red folder", "position", "left of console", .93, "Folder rests to the left of the radio console.", 19300),
    _obs("cur-jacket", "take-7", "wardrobe", "Mara's jacket", "state", "open", .98, "Jacket hangs open with buttons unfastened.", 5500),
    _obs("cur-dialogue", "take-7", "dialogue", "Mara line 18", "text", "omitted", .99, "No matching spoken line occurs before Mara crosses frame.", 28800),
    _obs("cur-phone", "take-7", "prop", "desk phone", "presence", "present", .96, "Black phone remains visible at frame left.", 22300),
    _obs("cur-clock", "take-7", "prop", "wall clock", "display", "11:48", .56, "Minute hand may indicate :48, but the face is soft.", 32100),
]


def workflow_steps(persistence_ok: bool = True, persistence_error: str | None = None) -> list[WorkflowStep]:
    names = [
        ("validate_assets", "Upload validator", "2 video fixtures and screenplay validated"),
        ("analyze_reference_take", "Fixture loader", "7 reference observations loaded; no Gemini call made"),
        ("analyze_new_take", "Fixture loader", "7 current observations loaded; no Gemini call made"),
        ("persist_observations", "clickhouse-connect", "Fixture observations persisted to local ClickHouse"),
        ("retrieve_continuity_history_through_mcp", "Demo fixture reader", "Skipped in Demo Mode; no MCP call claimed"),
        ("compare_observations", "Deterministic comparison", "5 blockers identified; low-confidence clock evidence excluded"),
        ("calculate_wrap_recommendation", "Deterministic policy", "Human review required"),
        ("await_human_review", "Human approval gate", "Waiting for script supervisor decisions"),
        ("generate_reports", "Report generator", "Draft report available; updates after review"),
    ]
    steps: list[WorkflowStep] = []
    for index, (name, tool, output) in enumerate(names):
        start = _NOW + timedelta(seconds=index * 2)
        waiting = name == "await_human_review"
        persistence_failed = name == "persist_observations" and not persistence_ok and persistence_error is not None
        persistence_waiting = name == "persist_observations" and not persistence_ok and persistence_error is None
        steps.append(WorkflowStep(
            name=name,
            status="failed" if persistence_failed else "waiting" if waiting or persistence_waiting else "complete",
            started_at=start,
            finished_at=None if waiting or persistence_waiting else start + timedelta(milliseconds=620),
            input_summary="Seeded demo production state",
            output_summary=(
                "ClickHouse persistence failed; review remains available from fixtures. Restart after checking database health."
                if persistence_failed else "Waiting for ClickHouse startup" if persistence_waiting else output
            ),
            tool_name=tool,
            error=persistence_error if persistence_failed else None,
        ))
    return steps


CURATED_ASSETS = {
    "reference": CuratedAsset(
        asset_id="reference", take_id="take-reference", label="Take 03 · Approved reference",
        role="reference", duration_ms=12000, playback_url="/api/assets/reference/playback",
        poster_variant="reference",
    ),
    "candidate-clean": CuratedAsset(
        asset_id="candidate-clean", take_id="take-clean", label="Take 07A · Clean candidate",
        role="candidate", duration_ms=12000, playback_url="/api/assets/candidate-clean/playback",
        poster_variant="clean",
    ),
    "candidate-flawed": CuratedAsset(
        asset_id="candidate-flawed", take_id="take-flawed", label="Take 07B · Pickup required",
        role="candidate", duration_ms=12000, playback_url="/api/assets/candidate-flawed/playback",
        poster_variant="flawed",
    ),
}


def release_gate_brief(request: DemoRunRequest) -> SceneBrief:
    return SceneBrief(
        production_id="prod-last-signal",
        production_title=request.production_title,
        scene_id="scene-24b",
        scene_heading=request.scene_heading,
        setup_id=request.setup_id,
        required_dialogue=request.required_dialogue,
        requirements=[
            SceneRequirement(
                requirement_id="mug-position", requirement_type=RequirementType.continuity,
                label="Red mug position", entity_name="red mug", attribute="screen_position",
            ),
            SceneRequirement(
                requirement_id="required-line", requirement_type=RequirementType.dialogue,
                label="Required dialogue", entity_name="performer", attribute="spoken_line",
                expected_value=request.required_dialogue,
            ),
        ],
    )


def _gate_observation(
    run_id: str, take_id: str, requirement_id: str, result: ObservationResult,
    value: str, confidence: float, evidence: str, start: int | None, end: int | None,
) -> RequirementObservation:
    return RequirementObservation(
        observation_id=f"{run_id}-{take_id}-{requirement_id}", run_id=run_id,
        production_id="prod-last-signal", scene_id="scene-24b", setup_id="Setup 24B-A",
        take_id=take_id, requirement_id=requirement_id, result=result,
        normalized_value=value, confidence=confidence, evidence_description=evidence,
        timestamp_start_ms=start, timestamp_end_ms=end, source="fixture",
    )


def fixture_gate_run(request: DemoRunRequest) -> tuple[WrapRun, list[RequirementObservation]]:
    run_id = str(uuid4())
    brief = release_gate_brief(request)
    reference = [
        _gate_observation(run_id, "take-reference", "mug-position", ObservationResult.observed,
                          "frame left", .98, "The red mug remains clearly visible at frame left.", 2400, 5200),
        _gate_observation(run_id, "take-reference", "required-line", ObservationResult.observed,
                          request.required_dialogue, .99, "The required line is audibly delivered.", 6500, 8500),
    ]
    if request.candidate_asset_id == "candidate-clean":
        candidate = [
            _gate_observation(run_id, "take-clean", "mug-position", ObservationResult.observed,
                              "frame left", .97, "The red mug matches the approved frame-left position.", 2500, 5300),
            _gate_observation(run_id, "take-clean", "required-line", ObservationResult.observed,
                              request.required_dialogue, .98, "The required line is audibly delivered.", 6400, 8600),
        ]
    else:
        candidate = [
            _gate_observation(run_id, "take-flawed", "mug-position", ObservationResult.observed,
                              "frame right", .97, "The red mug is clearly visible at frame right.", 2600, 5400),
            _gate_observation(run_id, "take-flawed", "required-line", ObservationResult.not_observed,
                              "not delivered", .99, "No occurrence of the required line was detected from 00:00–00:12.", 0, 12000),
        ]
    findings = evaluate_requirements(run_id, brief.requirements, reference, candidate)
    status, reason = gate_status(findings)
    run = WrapRun(
        run_id=run_id, mode="fixture",
        mode_disclaimer="Local scenario fixture. No Gemini, ADK, or MCP activity is claimed.",
        brief=brief, reference_asset=CURATED_ASSETS["reference"],
        candidate_asset=CURATED_ASSETS[request.candidate_asset_id],
        findings=findings, status=status, status_reason=reason, pickup_count=0,
        audit=[
            AuditEvent(step="validate_scene_brief", service="Pydantic", status="complete", duration_ms=3,
                       summary="Two declared requirements validated."),
            AuditEvent(step="analyze_curated_takes", service="Scenario fixture", status="complete", duration_ms=12,
                       summary="Grounded sample observations loaded; no model call made."),
            AuditEvent(step="retrieve_wrap_context", service="Not invoked in fixture mode", status="skipped", duration_ms=0,
                       summary="Live mode uses the official ClickHouse MCP server."),
            AuditEvent(step="evaluate_release_gate", service="Deterministic policy", status="complete", duration_ms=2,
                       summary=f"{len(findings)} actionable finding(s) produced."),
        ],
    )
    return run, reference + candidate
