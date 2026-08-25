import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.delivery_models import AssetKind, UploadAssetDeclaration
from app.delivery_service import inspect_file, validate_declaration
from app.handoff_fixtures import load_handoff_inputs
from app.handoff_gate import reconcile_media
from app.handoff_models import ExpectedTake, MediaCopy, MediaFile
from app.main import app


def _expected(run_id="run-1"):
    return ExpectedTake(
        expectation_id="exp-1", run_id=run_id, production="Film", shoot_day="Day 1",
        scene="24B", take=7, circled=True, camera_roll="A017", card_id="A017",
        video_filename="clip.mp4", sound_roll="SR12", audio_filename="take.wav",
        frame_rate="24", script_note="Circled",
    )


def _media(filename, kind, copies, run_id="run-1"):
    return MediaFile(
        media_id=filename, run_id=run_id, filename=filename, kind=kind,
        roll="A017" if kind == "video" else "SR12", card_id="A017" if kind == "video" else "SOUND",
        scene="24B", take=7, size_bytes=100, copies=copies,
    )


def test_two_distinct_matching_copies_are_verified():
    copies = [MediaCopy(destination="PRIMARY", checksum="abc", verified=True), MediaCopy(destination="SECONDARY", checksum="abc", verified=True)]
    video = _media("clip.mp4", "video", copies)
    audio = _media("take.wav", "audio", copies)
    checks, findings = reconcile_media("run-1", [_expected()], [video, audio])
    assert checks[0].verified_video_copies == 2
    assert checks[0].verified_audio_copies == 2
    assert findings == []


def test_one_copy_and_missing_audio_produce_exact_blockers():
    video = _media("clip.mp4", "video", [MediaCopy(destination="PRIMARY", checksum="abc", verified=True)])
    _, findings = reconcile_media("run-1", [_expected()], [video])
    assert sorted(item.issue_type.value for item in findings) == ["checksum_pending", "missing_audio"]


def test_conflicting_copy_hashes_fail_closed():
    copies = [MediaCopy(destination="PRIMARY", checksum="abc", verified=True), MediaCopy(destination="SECONDARY", checksum="xyz", verified=True)]
    video = _media("clip.mp4", "video", copies)
    audio = _media("take.wav", "audio", [MediaCopy(destination="A", checksum="1", verified=True), MediaCopy(destination="B", checksum="1", verified=True)])
    _, findings = reconcile_media("run-1", [_expected()], [video, audio])
    assert [item.issue_type.value for item in findings] == ["checksum_mismatch"]


def test_upload_declaration_rejects_wrong_role_and_large_report():
    with pytest.raises(HTTPException) as error:
        validate_declaration(UploadAssetDeclaration(kind=AssetKind.camera_report, filename="clip.mp4", content_type="video/mp4", size_bytes=100))
    assert error.value.status_code == 415
    with pytest.raises(HTTPException) as error:
        validate_declaration(UploadAssetDeclaration(kind=AssetKind.camera_report, filename="camera_report.csv", content_type="text/csv", size_bytes=11 * 1024 * 1024))
    assert error.value.status_code == 413


def test_file_magic_rejects_disguised_media(tmp_path):
    fake = tmp_path / "clip.mp4"
    fake.write_bytes(b"not a real mp4")
    with pytest.raises(HTTPException) as error:
        inspect_file(fake, AssetKind.camera_video)
    assert error.value.status_code == 415


def test_generated_demo_manifests_use_real_hashes():
    run_id = "real-assets"
    _, media, _ = load_handoff_inputs(run_id, "clean-handoff")
    asset_root = Path(__file__).parents[1] / "app" / "demo_assets"
    assert len(media) == 6
    for item in media:
        digest = hashlib.sha256((asset_root / item.filename).read_bytes()).hexdigest()
        assert len(item.verified_copies) == 2
        assert {copy.checksum for copy in item.verified_copies} == {digest}


def test_generated_problem_delivery_has_only_intended_gaps():
    expected, media, _ = load_handoff_inputs("problem-assets", "missing-media")
    _, findings = reconcile_media("problem-assets", expected, media)
    assert sorted(item.issue_type.value for item in findings) == ["checksum_pending", "missing_audio"]


def test_demo_packages_and_playback_are_served():
    with TestClient(app) as client:
        assert client.get("/api/demo-packages/problem").status_code == 200
        assert client.get("/api/demo-packages/recovered").status_code == 200
        assert client.get("/api/demo-assets/A017_C003_0825Q7.mp4").headers["content-type"].startswith("video/mp4")
        assert client.get("/api/demo-assets/SR12_024B_T05.wav").headers["content-type"].startswith("audio/wav")
