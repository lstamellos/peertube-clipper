from pathlib import Path
from uuid import uuid4

from clip_bridge.models import CandidateCreate, CandidateReview
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
