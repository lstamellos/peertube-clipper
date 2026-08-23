from pathlib import Path
from uuid import uuid4

from clip_bridge.models import AnalysisRunClaim, CandidateCreate, CandidateReview
from clip_bridge.storage import Storage


def test_shared_candidate_state_and_review(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()

    candidate = storage.create_candidate(
        video_uuid,
        CandidateCreate(
            anchor_start=10,
            anchor_end=15,
            suggested_start=5,
            suggested_end=30,
            canonical_transcript="Example canonical transcript.",
        ),
    )

    reviewed = storage.review_candidate(
        video_uuid,
        candidate["candidate_id"],
        CandidateReview(
            status="approved",
            editor_start=7,
            editor_end=28,
            acted_by_user_id=42,
        ),
    )

    assert reviewed is not None
    assert reviewed["status"] == "approved"
    assert reviewed["acted_by_user_id"] == 42
    assert storage.list_candidates(video_uuid)[0]["candidate_id"] == candidate["candidate_id"]


def test_analysis_claim_is_idempotent_and_stales_old_caption_revision(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()

    first_claim = AnalysisRunClaim(
        caption_language="el",
        caption_checksum="a" * 64,
        analyzer_version="locator-v1",
        model="qwen3:1.7b",
        prompt_version="anchors-v1",
    )

    first, created = storage.claim_analysis_run(video_uuid, first_claim)
    assert created is True
    assert first["status"] == "queued"
    assert storage.get_video(video_uuid)["status"] == "ready_for_analysis"

    repeated, repeated_created = storage.claim_analysis_run(video_uuid, first_claim)
    assert repeated_created is False
    assert repeated["analysis_run_id"] == first["analysis_run_id"]
    assert len(storage.list_analysis_runs(video_uuid)) == 1

    second_claim = AnalysisRunClaim(
        caption_language="el",
        caption_checksum="b" * 64,
        analyzer_version="locator-v1",
        model="qwen3:1.7b",
        prompt_version="anchors-v1",
    )

    second, second_created = storage.claim_analysis_run(video_uuid, second_claim)
    assert second_created is True
    assert second["analysis_run_id"] != first["analysis_run_id"]

    runs = storage.list_analysis_runs(video_uuid)
    by_id = {run["analysis_run_id"]: run for run in runs}
    assert by_id[first["analysis_run_id"]]["status"] == "stale"
    assert by_id[second["analysis_run_id"]]["status"] == "queued"


def test_delete_video_cascades_analysis_runs(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()

    storage.claim_analysis_run(
        video_uuid,
        AnalysisRunClaim(
            caption_language="en",
            caption_checksum="c" * 64,
            analyzer_version="locator-v1",
            model="qwen3:1.7b",
            prompt_version="anchors-v1",
        ),
    )

    assert len(storage.list_analysis_runs(video_uuid)) == 1
    assert storage.delete_video(video_uuid) is True
    assert storage.list_analysis_runs(video_uuid) == []
