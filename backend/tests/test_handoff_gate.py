from app.handoff_fixtures import fixture_handoff_run
from app.handoff_gate import handoff_status
from app.handoff_models import HandoffDecision, HandoffRunRequest


def test_missing_media_scenario_finds_exact_operational_blockers():
    run, _, _ = fixture_handoff_run(HandoffRunRequest(scenario_id="missing-media"))
    assert run.status == "hold_media"
    assert {item.issue_type.value for item in run.findings} == {"missing_audio", "checksum_pending"}
    missing = next(item for item in run.findings if item.issue_type == "missing_audio")
    assert "SR12_024B_T07.wav" in missing.required_action
    assert missing.scene_take == "24B / Take 7"


def test_clean_handoff_is_ready_but_not_auto_released():
    run, _, _ = fixture_handoff_run(HandoffRunRequest(scenario_id="clean-handoff"))
    assert run.findings == []
    assert run.status == "ready_for_release"
    assert run.released_by is None


def test_all_findings_require_human_resolution():
    run, _, _ = fixture_handoff_run(HandoffRunRequest(scenario_id="missing-media"))
    for finding in run.findings:
        finding.decision = HandoffDecision.recovered
    assert handoff_status(run.findings)[0] == "ready_for_release"
    run.findings[0].decision = HandoffDecision.needs_review
    assert handoff_status(run.findings)[0] == "needs_review"
