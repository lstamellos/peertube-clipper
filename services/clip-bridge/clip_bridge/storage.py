import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from .models import CandidateCreate, CandidateReview


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
