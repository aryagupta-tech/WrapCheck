import json
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

import clickhouse_connect

from .config import Settings
from .models import (
    Conflict, FindingDecision, Observation, RequirementObservation,
    ReviewDecision, SceneBrief, WorkflowStep, WrapFinding, WrapRun,
)
from .handoff_models import ExpectedTake, HandoffDecision, HandoffRun, MediaFile

logger = logging.getLogger(__name__)


class ClickHouseRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._lock = Lock()

    @property
    def client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = clickhouse_connect.get_client(
                        host=self.settings.clickhouse_host,
                        port=self.settings.clickhouse_port,
                        username=self.settings.clickhouse_user,
                        password=self.settings.clickhouse_password,
                        database=self.settings.clickhouse_database,
                        secure=self.settings.clickhouse_secure,
                        connect_timeout=self.settings.clickhouse_connect_timeout,
                        send_receive_timeout=self.settings.clickhouse_receive_timeout,
                        autogenerate_session_id=False,
                    )
        return self._client

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            logger.exception("ClickHouse health check failed")
            return False

    def seed_demo(self, production: dict[str, Any], observations: list[Observation], conflicts: list[Conflict]) -> None:
        self.client.insert(
            "productions",
            [[production["production_id"], production["title"], datetime.now(timezone.utc)]],
            column_names=["production_id", "title", "created_at"],
        )
        self.store_observations(observations)
        self.store_conflicts(conflicts)

    def store_observations(self, observations: list[Observation]) -> None:
        if not observations:
            return
        rows = []
        for item in observations:
            data = item.model_dump()
            data["source"] = str(data["source"])
            rows.append([data[column] for column in OBSERVATION_COLUMNS])
        self.client.insert("observations", rows, column_names=OBSERVATION_COLUMNS)

    def store_conflicts(self, conflicts: list[Conflict]) -> None:
        if conflicts:
            rows = [[
                item.conflict_id, item.production_id, item.scene_id,
                item.reference_observation_id, item.current_observation_id,
                item.entity_type, item.entity_name, item.attribute,
                item.reference_value, item.current_value, item.confidence,
                item.severity, item.deterministic_reason, datetime.now(timezone.utc),
            ] for item in conflicts]
            self.client.insert("conflicts", rows, column_names=CONFLICT_COLUMNS)

    def store_decision(self, conflict_id: str, decision: ReviewDecision, reviewer: str, note: str) -> None:
        self.client.insert(
            "human_decisions",
            [[conflict_id, decision.value, reviewer, note, datetime.now(timezone.utc)]],
            column_names=["conflict_id", "decision", "reviewer", "note", "created_at"],
        )

    def store_agent_run(
        self,
        production_id: str,
        scene_id: str,
        mode: str,
        model: str,
        steps: list[WorkflowStep],
    ) -> None:
        run_id = uuid4()
        started = min(step.started_at for step in steps)
        finished_values = [step.finished_at for step in steps if step.finished_at]
        finished = max(finished_values) if finished_values else None
        status = "failed" if any(step.status == "failed" for step in steps) else "waiting" if any(step.status == "waiting" for step in steps) else "complete"
        self.client.insert(
            "agent_runs",
            [[run_id, production_id, scene_id, mode, status, model, started, finished, ""]],
            column_names=["run_id", "production_id", "scene_id", "mode", "status", "model", "started_at", "finished_at", "error"],
        )
        self.client.insert(
            "tool_calls",
            [[
                uuid4(), run_id, step.name, step.tool_name, step.status,
                step.input_summary, step.output_summary, step.started_at,
                step.finished_at, step.error or "",
            ] for step in steps],
            column_names=[
                "call_id", "run_id", "step_name", "tool_name", "status", "input_summary",
                "output_summary", "started_at", "finished_at", "error",
            ],
        )

    def store_scene_requirements(self, brief: SceneBrief) -> None:
        now = datetime.now(timezone.utc)
        self.client.insert(
            "scene_requirements",
            [[
                item.requirement_id, brief.production_id, brief.scene_id, brief.setup_id,
                item.requirement_type.value, item.label, item.entity_name, item.attribute,
                item.expected_value or "", now,
            ] for item in brief.requirements],
            column_names=[
                "requirement_id", "production_id", "scene_id", "setup_id", "requirement_type",
                "label", "entity_name", "attribute", "expected_value", "created_at",
            ],
        )

    def store_requirement_observations(self, observations: list[RequirementObservation]) -> None:
        if not observations:
            return
        self.client.insert(
            "requirement_observations",
            [[
                item.observation_id, item.run_id, item.production_id, item.scene_id, item.setup_id,
                item.take_id, item.requirement_id, item.result.value, item.normalized_value,
                item.confidence, item.evidence_description, item.timestamp_start_ms,
                item.timestamp_end_ms, item.source, item.created_at,
            ] for item in observations],
            column_names=[
                "observation_id", "run_id", "production_id", "scene_id", "setup_id", "take_id",
                "requirement_id", "result", "normalized_value", "confidence",
                "evidence_description", "timestamp_start_ms", "timestamp_end_ms", "source", "created_at",
            ],
        )

    def store_wrap_run(self, run: WrapRun) -> None:
        self.client.insert(
            "wrap_checks",
            [[
                run.run_id, run.brief.production_id, run.brief.scene_id, run.brief.setup_id,
                run.reference_asset.take_id, run.candidate_asset.take_id, run.mode,
                run.status.value, run.status_reason, run.created_at, run.cleared_at,
                run.cleared_by or "",
            ]],
            column_names=[
                "run_id", "production_id", "scene_id", "setup_id", "reference_take_id",
                "candidate_take_id", "mode", "status", "status_reason", "created_at",
                "cleared_at", "cleared_by",
            ],
        )
        self.store_wrap_findings(run.findings)

    def store_wrap_findings(self, findings: list[WrapFinding]) -> None:
        if not findings:
            return
        now = datetime.now(timezone.utc)
        self.client.insert(
            "wrap_findings",
            [[
                item.finding_id, item.run_id, item.requirement_id, item.finding_type.value,
                item.requirement_type.value, item.label, item.expected_value, item.observed_value,
                item.reference_evidence, item.candidate_evidence, item.reference_timestamp_ms,
                item.candidate_timestamp_ms, item.inspected_start_ms, item.inspected_end_ms,
                item.confidence, item.severity, item.recommended_action, now,
            ] for item in findings],
            column_names=[
                "finding_id", "run_id", "requirement_id", "finding_type", "requirement_type",
                "label", "expected_value", "observed_value", "reference_evidence",
                "candidate_evidence", "reference_timestamp_ms", "candidate_timestamp_ms",
                "inspected_start_ms", "inspected_end_ms", "confidence", "severity",
                "recommended_action", "created_at",
            ],
        )

    def store_finding_decision(
        self, finding_id: str, decision: FindingDecision, reviewer: str, note: str,
    ) -> None:
        self.client.insert(
            "finding_decisions",
            [[finding_id, decision.value, reviewer, note, datetime.now(timezone.utc)]],
            column_names=["finding_id", "decision", "reviewer", "note", "created_at"],
        )

    def store_clearance(self, run: WrapRun, reviewer: str, note: str) -> None:
        self.client.insert(
            "wrap_clearances",
            [[run.run_id, reviewer, note, datetime.now(timezone.utc)]],
            column_names=["run_id", "reviewer", "note", "created_at"],
        )

    def demo_runs_in_window(self, session_hash: str, minutes: int = 10) -> int:
        result = self.client.query(
            "SELECT count() FROM demo_run_quota "
            "WHERE session_hash = {session_hash:String} "
            "AND created_at > now() - toIntervalMinute({minutes:UInt16})",
            parameters={"session_hash": session_hash, "minutes": minutes},
        )
        return int(result.first_row[0])

    def record_demo_run(self, session_hash: str, run_id: str) -> None:
        self.client.insert(
            "demo_run_quota",
            [[session_hash, run_id, datetime.now(timezone.utc)]],
            column_names=["session_hash", "run_id", "created_at"],
        )

    def public_events_in_window(self, session_hash: str, event_type: str, minutes: int = 10) -> tuple[int, int]:
        result = self.client.query(
            "SELECT countIf(session_hash = {session_hash:String}), count() FROM public_quota_events "
            "WHERE event_type = {event_type:String} AND created_at > now() - toIntervalMinute({minutes:UInt16})",
            parameters={"session_hash": session_hash, "event_type": event_type, "minutes": minutes},
        )
        return int(result.first_row[0]), int(result.first_row[1])

    def record_public_event(self, session_hash: str, event_type: str, resource_id: str) -> None:
        self.client.insert(
            "public_quota_events",
            [[session_hash, event_type, resource_id, datetime.now(timezone.utc)]],
            column_names=["session_hash", "event_type", "resource_id", "created_at"],
        )

    def store_handoff_inputs(self, expected: list[ExpectedTake], media: list[MediaFile]) -> None:
        if expected:
            self.client.insert("media_expectations", [[
                item.expectation_id, item.run_id, item.production, item.shoot_day, item.scene,
                item.take, item.circled, item.camera_roll, item.card_id, item.video_filename,
                item.sound_roll, item.audio_filename, item.frame_rate, item.script_note,
                datetime.now(timezone.utc),
            ] for item in expected], column_names=[
                "expectation_id", "run_id", "production", "shoot_day", "scene", "take",
                "circled", "camera_roll", "card_id", "video_filename", "sound_roll",
                "audio_filename", "frame_rate", "script_note", "created_at",
            ])
        if media:
            self.client.insert("media_inventory", [[
                item.media_id, item.run_id, item.filename, item.kind, item.roll, item.card_id,
                item.scene, item.take, item.size_bytes, item.checksum_state.value,
                next((copy.checksum for copy in item.verified_copies), ""),
                datetime.now(timezone.utc),
            ] for item in media], column_names=[
                "media_id", "run_id", "filename", "kind", "roll", "card_id", "scene",
                "take", "size_bytes", "checksum_state", "checksum", "created_at",
            ])

    def store_media_copies(self, media: list[MediaFile]) -> None:
        rows = [
            [item.media_id, item.run_id, item.filename, copy.destination,
             copy.checksum_algorithm, copy.checksum, copy.verified, copy.verified_at,
             datetime.now(timezone.utc)]
            for item in media for copy in item.copies
        ]
        if rows:
            self.client.insert("media_copies", rows, column_names=[
                "media_id", "run_id", "filename", "destination", "checksum_algorithm",
                "checksum", "verified", "verified_at", "created_at",
            ])

    def store_handoff_run(self, run: HandoffRun) -> None:
        self.client.insert("handoff_runs", [[
            run.run_id, run.production, run.shoot_day, run.delivery_name, run.mode,
            run.status.value, run.status_reason, run.created_at, run.released_at,
            run.released_by or "",
        ]], column_names=[
            "run_id", "production", "shoot_day", "delivery_name", "mode", "status",
            "status_reason", "created_at", "released_at", "released_by",
        ])
        if run.findings:
            self.client.insert("handoff_findings", [[
                item.finding_id, item.run_id, item.issue_type.value, item.severity, item.title,
                item.scene_take, item.card_id, item.expected, item.observed,
                json.dumps(item.evidence), item.required_action, datetime.now(timezone.utc),
            ] for item in run.findings], column_names=[
                "finding_id", "run_id", "issue_type", "severity", "title", "scene_take",
                "card_id", "expected", "observed", "evidence_json", "required_action", "created_at",
            ])

    def store_handoff_decision(self, finding_id: str, decision: HandoffDecision, reviewer: str, note: str) -> None:
        self.client.insert("handoff_decisions", [[
            finding_id, decision.value, reviewer, note, datetime.now(timezone.utc),
        ]], column_names=["finding_id", "decision", "reviewer", "note", "created_at"])

    def store_handoff_release(self, run_id: str, reviewer: str, note: str) -> None:
        self.client.insert("handoff_releases", [[
            run_id, reviewer, note, datetime.now(timezone.utc),
        ]], column_names=["run_id", "reviewer", "note", "created_at"])


OBSERVATION_COLUMNS = [
    "observation_id", "production_id", "scene_id", "shot_id", "take_id",
    "timestamp_start_ms", "timestamp_end_ms", "entity_type", "entity_name", "attribute",
    "observed_value", "confidence", "evidence_description", "evidence_frame_timestamp_ms",
    "source", "created_at",
]

CONFLICT_COLUMNS = [
    "conflict_id", "production_id", "scene_id", "reference_observation_id",
    "current_observation_id", "entity_type", "entity_name", "attribute",
    "reference_value", "current_value", "confidence", "severity",
    "deterministic_reason", "created_at",
]


class DecisionStore:
    """Process-local read model; every mutation is also appended to ClickHouse."""
    def __init__(self):
        self.values: dict[str, ReviewDecision] = {}

    def set(self, conflict_id: str, decision: ReviewDecision) -> None:
        self.values[conflict_id] = decision

    def get(self, conflict_id: str) -> ReviewDecision | None:
        return self.values.get(conflict_id)


class RunStore:
    """Process-local read model backed by append-only ClickHouse events."""

    def __init__(self):
        self.values: dict[str, WrapRun] = {}
        self._lock = Lock()

    def put(self, run: WrapRun) -> WrapRun:
        with self._lock:
            self.values[run.run_id] = run
        return run

    def get(self, run_id: str) -> WrapRun | None:
        return self.values.get(run_id)

    def find_by_finding(self, finding_id: str) -> WrapRun | None:
        return next((
            run for run in self.values.values()
            if any(item.finding_id == finding_id for item in run.findings)
        ), None)
