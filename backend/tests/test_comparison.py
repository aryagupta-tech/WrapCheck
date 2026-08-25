from app.comparison import compare_observations, recommendation
from app.fixtures import CURRENT_OBSERVATIONS, REFERENCE_OBSERVATIONS
from app.models import Observation, ReviewDecision


def copy_observation(source: Observation, **updates) -> Observation:
    return source.model_copy(update=updates)


def test_unknown_values_do_not_create_conflicts():
    current = copy_observation(CURRENT_OBSERVATIONS[0], observed_value="unknown")
    assert compare_observations([REFERENCE_OBSERVATIONS[0]], [current]) == []


def test_low_confidence_is_not_a_blocker():
    current = copy_observation(CURRENT_OBSERVATIONS[0], confidence=0.35)
    conflicts = compare_observations([REFERENCE_OBSERVATIONS[0]], [current])
    assert len(conflicts) == 1
    assert conflicts[0].severity == "review"


def test_matching_observations_do_not_create_conflicts():
    current = copy_observation(
        CURRENT_OBSERVATIONS[0], observed_value=REFERENCE_OBSERVATIONS[0].observed_value
    )
    assert compare_observations([REFERENCE_OBSERVATIONS[0]], [current]) == []


def test_five_seeded_mismatches_are_detected():
    conflicts = compare_observations(REFERENCE_OBSERVATIONS, CURRENT_OBSERVATIONS)
    assert len(conflicts) == 5
    assert all(conflict.severity == "blocking" for conflict in conflicts)


def test_human_overrides_update_recommendation():
    conflicts = compare_observations(REFERENCE_OBSERVATIONS, CURRENT_OBSERVATIONS)
    for conflict in conflicts:
        conflict.decision = ReviewDecision.intentional_change
    assert recommendation(conflicts)[0] == "safe_to_wrap"
    conflicts[0].decision = ReviewDecision.confirmed_error
    assert recommendation(conflicts)[0] == "do_not_wrap"
