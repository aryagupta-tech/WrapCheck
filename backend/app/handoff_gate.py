from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from .handoff_models import (
    ChecksumState, ExpectedTake, HandoffDecision, HandoffFinding, HandoffIssueType,
    HandoffRun, HandoffStatus, MediaFile, TakeCheck,
)


def reconcile_media(run_id: str, expected: list[ExpectedTake], media: list[MediaFile]):
    filename_counts = Counter(item.filename for item in media)
    by_filename = {item.filename: item for item in media}
    checks: list[TakeCheck] = []
    findings: list[HandoffFinding] = []
    checksum_cards: set[str] = set()

    for take in expected:
        video = by_filename.get(take.video_filename)
        audio = by_filename.get(take.audio_filename)
        scene_take = f"{take.scene} / Take {take.take}"
        video_state = video.checksum_state if video else ChecksumState.failed
        checks.append(TakeCheck(
            scene_take=scene_take,
            circled=take.circled,
            camera_roll=take.camera_roll,
            sound_roll=take.sound_roll,
            video_filename=take.video_filename,
            audio_filename=take.audio_filename,
            video_state="present" if video else "missing",
            audio_state="present" if audio else "missing",
            checksum_state=video_state,
            verified_video_copies=len(video.verified_copies) if video else 0,
            verified_audio_copies=len(audio.verified_copies) if audio else 0,
            video_playback_url=video.playback_url if video else None,
            audio_playback_url=audio.playback_url if audio else None,
            script_note=take.script_note,
        ))

        for filename, item in ((take.video_filename, video), (take.audio_filename, audio)):
            if item and filename_counts[filename] > 1:
                findings.append(_finding(
                    run_id, HandoffIssueType.duplicate_media, scene_take, item.card_id,
                    "One unambiguous inventory record is required per file.",
                    f"{filename} appears {filename_counts[filename]} times.",
                    [f"Inventory: {filename}", f"Duplicate rows: {filename_counts[filename]}"],
                    "Resolve the duplicate inventory records and rerun reconciliation.",
                ))

        if not video:
            findings.append(_finding(
                run_id, HandoffIssueType.missing_video, scene_take, take.card_id,
                "Camera report lists a recorded video file.",
                f"{take.video_filename} is absent from the delivery manifest.",
                [f"Camera report: {take.video_filename}", f"Card: {take.card_id}"],
                f"Recover {take.video_filename} from {take.card_id} before formatting the card.",
            ))
        if not audio:
            findings.append(_finding(
                run_id, HandoffIssueType.missing_audio, scene_take, take.card_id,
                f"Sound report expects {take.audio_filename} on {take.sound_roll}.",
                "No matching WAV file exists in the media manifest.",
                [f"Sound report: {take.audio_filename}", f"Script note: {take.script_note}"],
                f"Recover {take.audio_filename} from {take.sound_roll} and attach it to {scene_take}.",
            ))

        if video and not video.checksum_consistent:
            findings.append(_checksum_mismatch(run_id, scene_take, take.card_id, video))
        elif video and video.checksum_state != ChecksumState.verified and take.card_id not in checksum_cards:
            checksum_cards.add(take.card_id)
            findings.append(_checksum_pending(run_id, "All takes on card", take.card_id, video))

        if audio and not audio.checksum_consistent:
            findings.append(_checksum_mismatch(run_id, scene_take, take.sound_roll, audio))
        elif audio and audio.checksum_state != ChecksumState.verified:
            findings.append(_checksum_pending(run_id, scene_take, take.sound_roll, audio))

    return checks, findings


def _checksum_pending(run_id: str, scene_take: str, card_id: str, media: MediaFile):
    destinations = sorted({copy.destination for copy in media.verified_copies})
    return _finding(
        run_id, HandoffIssueType.checksum_pending, scene_take, card_id,
        "Every reported file must have matching verified checksums on two distinct destinations.",
        f"{media.filename} has {len(destinations)} verified destination(s): {', '.join(destinations) or 'none'}.",
        [f"Media manifest: {media.filename}", f"Verified destinations: {', '.join(destinations) or 'none'}"],
        f"Finish and verify both backup copies for {card_id}; do not erase the source media.",
    )


def _checksum_mismatch(run_id: str, scene_take: str, card_id: str, media: MediaFile):
    evidence = [f"{copy.destination}: {copy.checksum}" for copy in media.verified_copies]
    return _finding(
        run_id, HandoffIssueType.checksum_mismatch, scene_take, card_id,
        "Verified backup hashes must match.",
        f"{media.filename} has conflicting verified hashes.",
        evidence,
        f"Re-copy {media.filename}, recompute both hashes, and investigate possible corruption.",
    )


def _finding(run_id, issue_type, scene_take, card_id, expected, observed, evidence, action):
    finding_id = str(uuid5(NAMESPACE_URL, f"handoff:{run_id}:{issue_type}:{scene_take}:{card_id}"))
    return HandoffFinding(
        finding_id=finding_id,
        run_id=run_id,
        issue_type=issue_type,
        severity="blocking",
        title={
            HandoffIssueType.missing_video: "Camera file is missing",
            HandoffIssueType.missing_audio: "Matching production sound is missing",
            HandoffIssueType.checksum_pending: "Two-copy verification is incomplete",
            HandoffIssueType.checksum_mismatch: "Backup checksums do not match",
            HandoffIssueType.metadata_mismatch: "Slate metadata does not match",
            HandoffIssueType.duplicate_media: "Duplicate inventory records need review",
        }[issue_type],
        scene_take=scene_take,
        card_id=card_id,
        expected=expected,
        observed=observed,
        evidence=evidence,
        required_action=action,
    )


def handoff_status(findings: list[HandoffFinding], released: bool = False):
    if released:
        return HandoffStatus.released_by_dit, "A named DIT released this delivery after reviewing the evidence."
    if any(item.decision == HandoffDecision.needs_review for item in findings):
        return HandoffStatus.needs_review, "At least one discrepancy needs production review."
    unresolved = [item for item in findings if item.decision is None]
    if unresolved:
        return HandoffStatus.hold_media, f"{len(unresolved)} blocking media issue(s). Keep the source cards protected."
    return HandoffStatus.ready_for_release, "All discrepancies are resolved. The DIT may release the delivery."


def refresh_handoff(run: HandoffRun):
    run.status, run.status_reason = handoff_status(run.findings, bool(run.released_at))
    return run
