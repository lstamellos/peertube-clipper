import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from clip_bridge.models import AnalysisRunClaim, AnalysisRunUpdate, CandidateCreate, CandidateReview
from clip_bridge.storage import Storage


def analysis_claim(caption: bytes, analyzer_version: str = "locator-v1") -> AnalysisRunClaim:
    return AnalysisRunClaim(
        caption_language="el",
        caption_checksum=hashlib.sha256(caption).hexdigest(),
        analyzer_version=analyzer_version,
        model="qwen3:1.7b",
        prompt_version="anchors-v1",
    )


def candidate() -> CandidateCreate:
    return CandidateCreate(
        anchor_start=10,
        anchor_end=15,
        suggested_start=5,
        suggested_end=30,
        canonical_transcript="Example canonical transcript.",
    )


def test_shared_candidate_state_and_review(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()

    created = storage.create_candidate(video_uuid, candidate())

    reviewed = storage.review_candidate(
        video_uuid,
        created["candidate_id"],
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
    assert storage.list_candidates(video_uuid)[0]["candidate_id"] == created["candidate_id"]


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
    assert first["caption_snapshot_ready"] is False
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


def test_worker_claim_requires_matching_caption_snapshot(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    caption = b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n"

    run, _ = storage.claim_analysis_run(video_uuid, analysis_claim(caption))
    assert storage.claim_next_analysis_run() is None

    with pytest.raises(ValueError, match="checksum mismatch"):
        storage.attach_caption_snapshot(
            video_uuid,
            run["analysis_run_id"],
            b"WEBVTT\n\n00:00.000 --> 00:01.000\nDifferent\n",
        )

    attached = storage.attach_caption_snapshot(video_uuid, run["analysis_run_id"], caption)
    assert attached["caption_snapshot_ready"] is True

    claimed = storage.claim_next_analysis_run()
    assert claimed is not None
    assert claimed["analysis_run_id"] == run["analysis_run_id"]
    assert claimed["status"] == "analyzing"
    assert storage.get_video(video_uuid)["status"] == "analyzing"


def test_partial_analysis_candidates_are_hidden_until_run_completes(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nCanonical text\n"

    run, _ = storage.claim_analysis_run(video_uuid, analysis_claim(caption))
    storage.attach_caption_snapshot(video_uuid, run["analysis_run_id"], caption)
    claimed = storage.claim_next_analysis_run()
    assert claimed is not None

    created = storage.create_analysis_candidate(video_uuid, run["analysis_run_id"], candidate())
    assert created["analysis_run_id"] == run["analysis_run_id"]
    assert storage.list_candidates(video_uuid) == []

    completed = storage.update_analysis_run(
        video_uuid,
        run["analysis_run_id"],
        AnalysisRunUpdate(status="complete"),
    )
    assert completed is not None
    assert completed["status"] == "complete"
    assert storage.get_video(video_uuid)["status"] == "pending_review"
    assert len(storage.list_candidates(video_uuid)) == 1


def test_stale_analyzing_run_cannot_publish_or_finish(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    first_caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nOld revision\n"
    second_caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nNew revision\n"

    first, _ = storage.claim_analysis_run(video_uuid, analysis_claim(first_caption))
    storage.attach_caption_snapshot(video_uuid, first["analysis_run_id"], first_caption)
    claimed = storage.claim_next_analysis_run()
    assert claimed is not None

    storage.create_analysis_candidate(video_uuid, first["analysis_run_id"], candidate())

    second, created = storage.claim_analysis_run(video_uuid, analysis_claim(second_caption))
    assert created is True
    assert second["analysis_run_id"] != first["analysis_run_id"]

    by_id = {run["analysis_run_id"]: run for run in storage.list_analysis_runs(video_uuid)}
    assert by_id[first["analysis_run_id"]]["status"] == "stale"
    assert storage.list_candidates(video_uuid) == []

    with pytest.raises(ValueError, match="not writable"):
        storage.create_analysis_candidate(video_uuid, first["analysis_run_id"], candidate())

    with pytest.raises(ValueError, match="invalid analysis transition"):
        storage.update_analysis_run(
            video_uuid,
            first["analysis_run_id"],
            AnalysisRunUpdate(status="complete"),
        )


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
