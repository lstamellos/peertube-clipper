import hashlib
import sqlite3
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
        category="quote",
        analysis_reason="Editorially useful statement.",
    )


def claim_worker(storage: Storage):
    claimed = storage.claim_next_analysis_run()
    assert claimed is not None
    return claimed


def test_phase2b_schema_migrates_without_losing_queued_run(tmp_path: Path) -> None:
    database = tmp_path / "phase2b.sqlite3"
    video_uuid = str(uuid4())
    run_id = str(uuid4())
    now = "2026-08-23T03:39:17+00:00"

    db = sqlite3.connect(database)
    try:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE videos (
                video_uuid TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE candidates (
                candidate_id TEXT PRIMARY KEY,
                video_uuid TEXT NOT NULL REFERENCES videos(video_uuid) ON DELETE CASCADE,
                anchor_start REAL NOT NULL,
                anchor_end REAL NOT NULL,
                suggested_start REAL NOT NULL,
                suggested_end REAL NOT NULL,
                canonical_transcript TEXT NOT NULL,
                status TEXT NOT NULL,
                editor_start REAL,
                editor_end REAL,
                acted_by_user_id INTEGER,
                acted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE analysis_runs (
                analysis_run_id TEXT PRIMARY KEY,
                video_uuid TEXT NOT NULL REFERENCES videos(video_uuid) ON DELETE CASCADE,
                caption_language TEXT NOT NULL,
                caption_checksum TEXT NOT NULL,
                analyzer_version TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(video_uuid, caption_checksum, analyzer_version)
            );
            """
        )
        db.execute(
            "INSERT INTO videos VALUES (?, 'ready_for_analysis', ?, ?)",
            (video_uuid, now, now),
        )
        db.execute(
            """
            INSERT INTO analysis_runs VALUES (?, ?, 'el', ?, 'locator-v1',
                'qwen3:1.7b', 'anchors-v1', 'queued', NULL, ?, ?)
            """,
            (run_id, video_uuid, "a" * 64, now, now),
        )
        db.commit()
    finally:
        db.close()

    storage = Storage(str(database))
    runs = storage.list_analysis_runs(video_uuid)
    assert len(runs) == 1
    assert runs[0]["analysis_run_id"] == run_id
    assert runs[0]["status"] == "queued"
    assert runs[0]["caption_snapshot_ready"] is False

    with storage.connect() as migrated:
        run_columns = {row["name"] for row in migrated.execute('PRAGMA table_info("analysis_runs")')}
        candidate_columns = {row["name"] for row in migrated.execute('PRAGMA table_info("candidates")')}
    assert {"caption_vtt", "worker_lease_token", "worker_lease_expires_at"} <= run_columns
    assert {"analysis_run_id", "category", "analysis_reason"} <= candidate_columns


def test_shared_candidate_state_and_review(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    created = storage.create_candidate(video_uuid, candidate())
    assert created["category"] == "quote"
    assert created["analysis_reason"] == "Editorially useful statement."
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

    by_id = {run["analysis_run_id"]: run for run in storage.list_analysis_runs(video_uuid)}
    assert by_id[first["analysis_run_id"]]["status"] == "stale"
    assert by_id[second["analysis_run_id"]]["status"] == "queued"


def test_new_analyzer_version_stales_previous_generation(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    caption = b"WEBVTT\n\n00:00.000 --> 00:01.000\nSame revision\n"

    first, _ = storage.claim_analysis_run(video_uuid, analysis_claim(caption, "locator-v1"))
    second, created = storage.claim_analysis_run(video_uuid, analysis_claim(caption, "locator-v2"))
    assert created is True
    assert second["analysis_run_id"] != first["analysis_run_id"]

    by_id = {run["analysis_run_id"]: run for run in storage.list_analysis_runs(video_uuid)}
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

    claimed, lease = claim_worker(storage)
    assert claimed["analysis_run_id"] == run["analysis_run_id"]
    assert claimed["status"] == "analyzing"
    assert lease
    assert storage.get_video(video_uuid)["status"] == "analyzing"
    assert storage.heartbeat_analysis_run(video_uuid, run["analysis_run_id"], lease)["status"] == "analyzing"


def test_partial_analysis_candidates_are_hidden_until_run_completes(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nCanonical text\n"
    run, _ = storage.claim_analysis_run(video_uuid, analysis_claim(caption))
    storage.attach_caption_snapshot(video_uuid, run["analysis_run_id"], caption)
    _, lease = claim_worker(storage)

    created = storage.create_analysis_candidate(video_uuid, run["analysis_run_id"], lease, candidate())
    assert created["analysis_run_id"] == run["analysis_run_id"]
    assert created["category"] == "quote"
    assert storage.list_candidates(video_uuid) == []

    completed = storage.finish_analysis_run(
        video_uuid,
        run["analysis_run_id"],
        lease,
        AnalysisRunUpdate(status="complete"),
    )
    assert completed["status"] == "complete"
    assert storage.get_video(video_uuid)["status"] == "pending_review"
    visible = storage.list_candidates(video_uuid)
    assert len(visible) == 1
    assert visible[0]["analysis_reason"] == "Editorially useful statement."


def test_stale_analyzing_run_cannot_publish_or_finish(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    first_caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nOld revision\n"
    second_caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nNew revision\n"

    first, _ = storage.claim_analysis_run(video_uuid, analysis_claim(first_caption))
    storage.attach_caption_snapshot(video_uuid, first["analysis_run_id"], first_caption)
    _, lease = claim_worker(storage)
    stored = storage.create_analysis_candidate(video_uuid, first["analysis_run_id"], lease, candidate())

    second, created = storage.claim_analysis_run(video_uuid, analysis_claim(second_caption))
    assert created is True
    assert second["analysis_run_id"] != first["analysis_run_id"]

    by_id = {run["analysis_run_id"]: run for run in storage.list_analysis_runs(video_uuid)}
    assert by_id[first["analysis_run_id"]]["status"] == "stale"
    assert storage.list_candidates(video_uuid) == []

    with storage.connect() as db:
        persisted = db.execute("SELECT * FROM candidates WHERE candidate_id = ?", (stored["candidate_id"],)).fetchone()
        assert persisted is not None
        assert persisted["status"] == "suggested"

    with pytest.raises(ValueError, match="lease is inactive"):
        storage.create_analysis_candidate(video_uuid, first["analysis_run_id"], lease, candidate())
    with pytest.raises(ValueError, match="lease is inactive"):
        storage.finish_analysis_run(
            video_uuid,
            first["analysis_run_id"],
            lease,
            AnalysisRunUpdate(status="complete"),
        )


def test_expired_worker_lease_requeues_and_discards_partial_candidates(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "clipper.sqlite3"))
    video_uuid = uuid4()
    caption = b"WEBVTT\n\n00:10.000 --> 00:15.000\nRecover me\n"
    run, _ = storage.claim_analysis_run(video_uuid, analysis_claim(caption))
    storage.attach_caption_snapshot(video_uuid, run["analysis_run_id"], caption)
    _, first_lease = claim_worker(storage)
    storage.create_analysis_candidate(video_uuid, run["analysis_run_id"], first_lease, candidate())

    with storage.connect() as db:
        db.execute(
            "UPDATE analysis_runs SET worker_lease_expires_at = ? WHERE analysis_run_id = ?",
            ("2000-01-01T00:00:00+00:00", run["analysis_run_id"]),
        )

    reclaimed, second_lease = claim_worker(storage)
    assert reclaimed["analysis_run_id"] == run["analysis_run_id"]
    assert reclaimed["status"] == "analyzing"
    assert second_lease != first_lease
    assert storage.list_candidates(video_uuid) == []

    with storage.connect() as db:
        count = db.execute("SELECT COUNT(*) AS count FROM candidates WHERE analysis_run_id = ?", (run["analysis_run_id"],)).fetchone()["count"]
        assert count == 0

    with pytest.raises(ValueError, match="lease is inactive"):
        storage.create_analysis_candidate(video_uuid, run["analysis_run_id"], first_lease, candidate())


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
