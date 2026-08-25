from uuid import uuid5, NAMESPACE_URL

from .models import Conflict, Observation, ReviewDecision


UNKNOWN_VALUES = {"unknown", "uncertain", "not_visible", "not visible", ""}


def compare_observations(
    reference: list[Observation],
    current: list[Observation],
    threshold: float = 0.8,
) -> list[Conflict]:
    """Compare matching scene/entity/attribute keys without model judgment."""
    reference_by_key = {
        (item.scene_id, item.entity_type.lower(), item.entity_name.lower(), item.attribute.lower()): item
        for item in reference
    }
    conflicts: list[Conflict] = []
    for item in current:
        key = (item.scene_id, item.entity_type.lower(), item.entity_name.lower(), item.attribute.lower())
        expected = reference_by_key.get(key)
        if not expected:
            continue
        expected_value = expected.observed_value.strip().lower()
        current_value = item.observed_value.strip().lower()
        if expected_value in UNKNOWN_VALUES or current_value in UNKNOWN_VALUES or expected_value == current_value:
            continue
        confidence = min(expected.confidence, item.confidence)
        severity = "blocking" if confidence >= threshold else "review"
        stable_id = uuid5(NAMESPACE_URL, f"{expected.observation_id}:{item.observation_id}")
        conflicts.append(
            Conflict(
                conflict_id=str(stable_id),
                production_id=item.production_id,
                scene_id=item.scene_id,
                reference_observation_id=expected.observation_id,
                current_observation_id=item.observation_id,
                entity_type=item.entity_type,
                entity_name=item.entity_name,
                attribute=item.attribute,
                reference_value=expected.observed_value,
                current_value=item.observed_value,
                reference_evidence=expected.evidence_description,
                current_evidence=item.evidence_description,
                reference_timestamp_ms=expected.evidence_frame_timestamp_ms,
                current_timestamp_ms=item.evidence_frame_timestamp_ms,
                confidence=confidence,
                severity=severity,
                deterministic_reason=(
                    "Values differ and both observations meet the blocking confidence threshold."
                    if severity == "blocking"
                    else "Values differ, but confidence is below the blocking threshold."
                ),
            )
        )
    return conflicts


def recommendation(conflicts: list[Conflict]) -> tuple[str, str]:
    unresolved_blockers = [
        conflict
        for conflict in conflicts
        if conflict.severity == "blocking"
        and conflict.decision not in {ReviewDecision.intentional_change}
    ]
    if any(conflict.decision is None for conflict in conflicts):
        return "needs_review", "Human review is required before the setup can wrap."
    if unresolved_blockers:
        return "do_not_wrap", f"{len(unresolved_blockers)} confirmed or unresolved blocking conflict(s) remain."
    return "safe_to_wrap", "All blocking differences were resolved as intentional changes."
