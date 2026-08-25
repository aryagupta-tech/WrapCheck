"""Deterministic wrap-gate policy for requirement-scoped observations."""

from uuid import NAMESPACE_URL, uuid5

from .models import (
    FindingDecision, FindingType, GateStatus, ObservationResult,
    RequirementObservation, RequirementType, SceneRequirement, WrapFinding,
)


def _normal(value: str) -> str:
    return " ".join(value.casefold().strip().rstrip(".!?").split())


def evaluate_requirements(
    run_id: str,
    requirements: list[SceneRequirement],
    reference: list[RequirementObservation],
    candidate: list[RequirementObservation],
    threshold: float = 0.8,
) -> list[WrapFinding]:
    """Return only actionable differences; unknown evidence is never blocking."""
    references = {item.requirement_id: item for item in reference}
    candidates = {item.requirement_id: item for item in candidate}
    findings: list[WrapFinding] = []
    for requirement in requirements:
        expected_observation = references.get(requirement.requirement_id)
        observed = candidates.get(requirement.requirement_id)
        expected_value = requirement.expected_value or (
            expected_observation.normalized_value if expected_observation else "not established"
        )
        confidence = (
            min(expected_observation.confidence if expected_observation else 0.0, observed.confidence if observed else 0.0)
            if requirement.requirement_type == RequirementType.continuity
            else observed.confidence if observed else 0.0
        )
        is_uncertain = (
            observed is None
            or observed.result == ObservationResult.uncertain
            or confidence < threshold
            or (
                requirement.requirement_type == RequirementType.continuity
                and (expected_observation is None or expected_observation.result != ObservationResult.observed)
            )
        )
        if is_uncertain:
            finding_type = FindingType.uncertain
            severity = "review"
            observed_value = observed.normalized_value if observed else "no observation returned"
            action = "Review the take in the player; evidence was not strong enough to create a pickup."
        elif requirement.requirement_type == RequirementType.dialogue:
            if observed.result == ObservationResult.observed:
                continue
            finding_type = FindingType.missing_required_beat
            severity = "blocking"
            observed_value = observed.normalized_value or "not delivered"
            action = f'Record a pickup containing the required line: “{expected_value}”'
        elif observed.result != ObservationResult.observed:
            finding_type = FindingType.uncertain
            severity = "review"
            observed_value = observed.normalized_value or "not visible"
            action = "Review the prop continuity manually before releasing the setup."
        elif _normal(expected_value) == _normal(observed.normalized_value):
            continue
        else:
            finding_type = FindingType.mismatch
            severity = "blocking"
            observed_value = observed.normalized_value
            action = f"Reset {requirement.entity_name} to {expected_value} and record a pickup."

        identity = uuid5(NAMESPACE_URL, f"{run_id}:{requirement.requirement_id}")
        findings.append(WrapFinding(
            finding_id=str(identity),
            run_id=run_id,
            requirement_id=requirement.requirement_id,
            finding_type=finding_type,
            requirement_type=requirement.requirement_type,
            label=requirement.label,
            expected_value=expected_value,
            observed_value=observed_value,
            reference_evidence=expected_observation.evidence_description if expected_observation else "The scene brief defines this required beat.",
            candidate_evidence=observed.evidence_description if observed else "The analyzer returned no grounded observation.",
            reference_timestamp_ms=expected_observation.timestamp_start_ms if expected_observation else None,
            candidate_timestamp_ms=observed.timestamp_start_ms if observed else None,
            inspected_start_ms=(observed.timestamp_start_ms or 0) if observed else 0,
            inspected_end_ms=(observed.timestamp_end_ms or 0) if observed else 0,
            confidence=confidence,
            severity=severity,
            recommended_action=action,
        ))
    return findings


def gate_status(findings: list[WrapFinding], cleared: bool = False) -> tuple[GateStatus, str]:
    if cleared:
        return GateStatus.cleared_by_supervisor, "A script supervisor explicitly cleared this setup."
    if any(item.decision == FindingDecision.needs_review for item in findings):
        return GateStatus.needs_supervisor_review, "A finding was escalated for supervisor review."
    blocking = [
        item for item in findings
        if item.severity == "blocking"
        and item.decision in {None, FindingDecision.pickup}
    ]
    if blocking:
        return GateStatus.hold_setup, f"{len(blocking)} blocking pickup item(s) remain. Keep the setup available."
    review = [
        item for item in findings
        if item.severity == "review" and item.decision != FindingDecision.intentional_change
    ]
    if review:
        return GateStatus.needs_supervisor_review, "Uncertain evidence needs a supervisor decision."
    return GateStatus.ready_for_supervisor_signoff, "No unresolved blocking evidence remains. A supervisor may clear the setup."


def refresh_run_state(run):
    run.status, run.status_reason = gate_status(run.findings, bool(run.cleared_at))
    run.pickup_count = sum(item.decision == FindingDecision.pickup for item in run.findings)
    return run
