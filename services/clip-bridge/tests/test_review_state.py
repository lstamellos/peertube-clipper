from uuid import UUID

from clip_bridge.models import CandidateCreate, CandidateReview
from clip_bridge.storage import Storage


VIDEO = UUID("11111111-1111-4111-8111-111111111111")


def candidate() -> CandidateCreate:
    return CandidateCreate(
        anchor_start=10,
        anchor_end=13,
        suggested_start=5,
        suggested_end=25,
        canonical_transcript="Canonical source excerpt",
    )


def test_candidate_transitions_update_shared_video_state(tmp_path):
    store = Storage(str(tmp_path / "state.sqlite3"))
    created = store.create_candidate(VIDEO, candidate())

    assert store.get_video(VIDEO)["status"] == "pending_review"

    store.review_candidate(
        VIDEO,
        created["candidate_id"],
        CandidateReview(
            status="edited",
            editor_start=6,
            editor_end=24,
            acted_by_user_id=42,
        ),
    )
    assert store.get_video(VIDEO)["status"] == "pending_review"

    reviewed = store.review_candidate(
        VIDEO,
        created["candidate_id"],
        CandidateReview(
            status="approved",
            editor_start=6,
            editor_end=24,
            acted_by_user_id=42,
        ),
    )

    assert reviewed["acted_by_user_id"] == 42
    assert store.get_video(VIDEO)["status"] == "reviewed"


def test_delete_video_cascades_candidate_state(tmp_path):
    store = Storage(str(tmp_path / "state.sqlite3"))
    store.create_candidate(VIDEO, candidate())

    assert len(store.list_candidates(VIDEO)) == 1
    assert store.delete_video(VIDEO) is True
    assert store.get_video(VIDEO) is None
    assert store.list_candidates(VIDEO) == []
    assert store.delete_video(VIDEO) is False
