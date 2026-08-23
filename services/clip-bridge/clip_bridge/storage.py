import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from .models import AnalysisRunClaim, AnalysisRunUpdate, CandidateCreate, CandidateReview


class Storage:
    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    video_uuid TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidates (
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

                CREATE TABLE IF NOT EXISTS analysis_runs (
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

                CREATE INDEX IF NOT EXISTS analysis_runs_video_uuid_idx
                    ON analysis_runs(video_uuid, created_at);
                """
            )

    def ensure_video(self, video_uuid: UUID) -> dict:
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO videos(video_uuid, status, created_at, updated_at)
                VALUES (?, 'waiting_for_video', ?, ?)
                ON CONFLICT(video_uuid) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (str(video_uuid), now, now),
            )
            row = db.execute(
                "SELECT * FROM videos WHERE video_uuid = ?",
                (str(video_uuid),),
            ).fetchone()
            return dict(row)

    def set_video_status(self, video_uuid: UUID, status: str) -> dict:
        self.ensure_video(video_uuid)
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            db.execute(
                "UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?",
                (status, now, str(video_uuid)),
            )
            row = db.execute(
                "SELECT * FROM videos WHERE video_uuid = ?",
                (str(video_uuid),),
            ).fetchone()
            return dict(row)

    def list_videos(self, statuses: list[str] | None = None) -> list[dict]:
        with self.connect() as db:
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                rows = db.execute(
                    f"SELECT * FROM videos WHERE status IN ({placeholders}) ORDER BY updated_at, video_uuid",
                    tuple(statuses),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM videos ORDER BY updated_at, video_uuid"
                ).fetchall()
            return [dict(row) for row in rows]

    def get_video(self, video_uuid: UUID) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM videos WHERE video_uuid = ?",
                (str(video_uuid),),
            ).fetchone()
            return dict(row) if row else None

    def delete_video(self, video_uuid: UUID) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM videos WHERE video_uuid = ?",
                (str(video_uuid),),
            )
            return cursor.rowcount > 0

    def list_candidates(self, video_uuid: UUID) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM candidates WHERE video_uuid = ? ORDER BY suggested_start, created_at",
                (str(video_uuid),),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_candidate(self, video_uuid: UUID, candidate: CandidateCreate) -> dict:
        self.ensure_video(video_uuid)
        candidate_id = str(uuid4())
        now = datetime.now(UTC).isoformat()

        if candidate.anchor_end <= candidate.anchor_start:
            raise ValueError("anchor_end must be greater than anchor_start")
        if candidate.suggested_end <= candidate.suggested_start:
            raise ValueError("suggested_end must be greater than suggested_start")

        with self.connect() as db:
            db.execute(
                """
                INSERT INTO candidates(
                    candidate_id, video_uuid,
                    anchor_start, anchor_end,
                    suggested_start, suggested_end,
                    canonical_transcript, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'suggested', ?, ?)
                """,
                (
                    candidate_id,
                    str(video_uuid),
                    candidate.anchor_start,
                    candidate.anchor_end,
                    candidate.suggested_start,
                    candidate.suggested_end,
                    candidate.canonical_transcript,
                    now,
                    now,
                ),
            )
            db.execute(
                "UPDATE videos SET status = 'pending_review', updated_at = ? WHERE video_uuid = ?",
                (now, str(video_uuid)),
            )
            row = db.execute(
                "SELECT * FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            return dict(row)

    def review_candidate(self, video_uuid: UUID, candidate_id: str, review: CandidateReview) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            current = db.execute(
                "SELECT * FROM candidates WHERE candidate_id = ? AND video_uuid = ?",
                (candidate_id, str(video_uuid)),
            ).fetchone()
            if not current:
                return None

            editor_start = review.editor_start
            editor_end = review.editor_end
            if review.status in {"edited", "approved"}:
                if editor_start is not None and editor_end is not None and editor_end <= editor_start:
                    raise ValueError("editor_end must be greater than editor_start")

            db.execute(
                """
                UPDATE candidates
                SET status = ?, editor_start = ?, editor_end = ?,
                    acted_by_user_id = ?, acted_at = ?, updated_at = ?
                WHERE candidate_id = ? AND video_uuid = ?
                """,
                (
                    review.status,
                    editor_start,
                    editor_end,
                    review.acted_by_user_id,
                    now,
                    now,
                    candidate_id,
                    str(video_uuid),
                ),
            )
            pending = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM candidates
                WHERE video_uuid = ? AND status IN ('suggested', 'edited')
                """,
                (str(video_uuid),),
            ).fetchone()["count"]
            video_status = "pending_review" if pending else "reviewed"
            db.execute(
                "UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?",
                (video_status, now, str(video_uuid)),
            )
            row = db.execute(
                "SELECT * FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            return dict(row)

    def list_analysis_runs(self, video_uuid: UUID) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM analysis_runs
                WHERE video_uuid = ?
                ORDER BY created_at DESC, analysis_run_id DESC
                """,
                (str(video_uuid),),
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_analysis_run(self, video_uuid: UUID, claim: AnalysisRunClaim) -> tuple[dict, bool]:
        self.ensure_video(video_uuid)
        now = datetime.now(UTC).isoformat()
        analysis_run_id = str(uuid4())

        with self.connect() as db:
            existing = db.execute(
                """
                SELECT * FROM analysis_runs
                WHERE video_uuid = ? AND caption_checksum = ? AND analyzer_version = ?
                LIMIT 1
                """,
                (str(video_uuid), claim.caption_checksum, claim.analyzer_version),
            ).fetchone()
            if existing:
                return dict(existing), False

            db.execute(
                """
                UPDATE analysis_runs
                SET status = 'stale', updated_at = ?
                WHERE video_uuid = ?
                  AND caption_checksum <> ?
                  AND status <> 'stale'
                """,
                (now, str(video_uuid), claim.caption_checksum),
            )

            try:
                db.execute(
                    """
                    INSERT INTO analysis_runs(
                        analysis_run_id, video_uuid,
                        caption_language, caption_checksum,
                        analyzer_version, model, prompt_version,
                        status, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', NULL, ?, ?)
                    """,
                    (
                        analysis_run_id,
                        str(video_uuid),
                        claim.caption_language,
                        claim.caption_checksum,
                        claim.analyzer_version,
                        claim.model,
                        claim.prompt_version,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = db.execute(
                    """
                    SELECT * FROM analysis_runs
                    WHERE video_uuid = ? AND caption_checksum = ? AND analyzer_version = ?
                    LIMIT 1
                    """,
                    (str(video_uuid), claim.caption_checksum, claim.analyzer_version),
                ).fetchone()
                if not existing:
                    raise
                return dict(existing), False

            db.execute(
                "UPDATE videos SET status = 'ready_for_analysis', updated_at = ? WHERE video_uuid = ?",
                (now, str(video_uuid)),
            )
            row = db.execute(
                "SELECT * FROM analysis_runs WHERE analysis_run_id = ?",
                (analysis_run_id,),
            ).fetchone()
            return dict(row), True

    def update_analysis_run(
        self,
        video_uuid: UUID,
        analysis_run_id: str,
        update: AnalysisRunUpdate,
    ) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            current = db.execute(
                """
                SELECT * FROM analysis_runs
                WHERE analysis_run_id = ? AND video_uuid = ?
                """,
                (analysis_run_id, str(video_uuid)),
            ).fetchone()
            if not current:
                return None

            db.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error = ?, updated_at = ?
                WHERE analysis_run_id = ? AND video_uuid = ?
                """,
                (
                    update.status,
                    update.error,
                    now,
                    analysis_run_id,
                    str(video_uuid),
                ),
            )

            if update.status == "queued":
                video_status = "ready_for_analysis"
            elif update.status == "analyzing":
                video_status = "analyzing"
            elif update.status == "failed":
                video_status = "partial_failure"
            elif update.status == "complete":
                candidate_count = db.execute(
                    "SELECT COUNT(*) AS count FROM candidates WHERE video_uuid = ?",
                    (str(video_uuid),),
                ).fetchone()["count"]
                video_status = "pending_review" if candidate_count else "reviewed"
            else:
                video_status = None

            if video_status:
                db.execute(
                    "UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?",
                    (video_status, now, str(video_uuid)),
                )

            row = db.execute(
                "SELECT * FROM analysis_runs WHERE analysis_run_id = ?",
                (analysis_run_id,),
            ).fetchone()
            return dict(row)
