import hashlib
import hmac
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from .models import AnalysisRunClaim, AnalysisRunUpdate, CandidateCreate, CandidateReview


MAX_CAPTION_BYTES = 20 * 1024 * 1024
WORKER_LEASE_SECONDS = 1200


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
                    caption_vtt BLOB,
                    worker_lease_token TEXT,
                    worker_lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(video_uuid, caption_checksum, analyzer_version)
                );

                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    video_uuid TEXT NOT NULL REFERENCES videos(video_uuid) ON DELETE CASCADE,
                    analysis_run_id TEXT,
                    anchor_start REAL NOT NULL,
                    anchor_end REAL NOT NULL,
                    suggested_start REAL NOT NULL,
                    suggested_end REAL NOT NULL,
                    canonical_transcript TEXT NOT NULL,
                    category TEXT,
                    analysis_reason TEXT,
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
            self._ensure_column(db, "analysis_runs", "caption_vtt", "BLOB")
            self._ensure_column(db, "analysis_runs", "worker_lease_token", "TEXT")
            self._ensure_column(db, "analysis_runs", "worker_lease_expires_at", "TEXT")
            self._ensure_column(db, "candidates", "analysis_run_id", "TEXT")
            self._ensure_column(db, "candidates", "category", "TEXT")
            self._ensure_column(db, "candidates", "analysis_reason", "TEXT")
            db.executescript(
                """
                CREATE INDEX IF NOT EXISTS analysis_runs_video_uuid_idx
                    ON analysis_runs(video_uuid, created_at);
                CREATE INDEX IF NOT EXISTS candidates_analysis_run_idx
                    ON candidates(analysis_run_id, suggested_start);
                """
            )

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in db.execute(f'PRAGMA table_info("{table}")').fetchall()}
        if column not in columns:
            db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')

    @staticmethod
    def _analysis_run_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        snapshot = result.pop("caption_vtt", None)
        result.pop("worker_lease_token", None)
        result.pop("worker_lease_expires_at", None)
        result["caption_snapshot_ready"] = snapshot is not None
        return result

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _lease_matches(row: sqlite3.Row, lease_token: str, now_iso: str) -> bool:
        actual = row["worker_lease_token"] or ""
        expires = row["worker_lease_expires_at"] or ""
        return (
            row["status"] == "analyzing"
            and bool(actual)
            and bool(lease_token)
            and hmac.compare_digest(actual, lease_token)
            and expires > now_iso
        )

    def ensure_video(self, video_uuid: UUID) -> dict:
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO videos(video_uuid, status, created_at, updated_at)
                VALUES (?, 'waiting_for_video', ?, ?)
                ON CONFLICT(video_uuid) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (str(video_uuid), now, now),
            )
            return dict(db.execute("SELECT * FROM videos WHERE video_uuid = ?", (str(video_uuid),)).fetchone())

    def set_video_status(self, video_uuid: UUID, status: str) -> dict:
        self.ensure_video(video_uuid)
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute("UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?", (status, now, str(video_uuid)))
            return dict(db.execute("SELECT * FROM videos WHERE video_uuid = ?", (str(video_uuid),)).fetchone())

    def list_videos(self, statuses: list[str] | None = None) -> list[dict]:
        with self.connect() as db:
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                rows = db.execute(
                    f"SELECT * FROM videos WHERE status IN ({placeholders}) ORDER BY updated_at, video_uuid",
                    tuple(statuses),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM videos ORDER BY updated_at, video_uuid").fetchall()
            return [dict(row) for row in rows]

    def get_video(self, video_uuid: UUID) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM videos WHERE video_uuid = ?", (str(video_uuid),)).fetchone()
            return dict(row) if row else None

    def delete_video(self, video_uuid: UUID) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM videos WHERE video_uuid = ?", (str(video_uuid),)).rowcount > 0

    def list_candidates(self, video_uuid: UUID) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT c.*
                FROM candidates c
                LEFT JOIN analysis_runs a ON a.analysis_run_id = c.analysis_run_id
                WHERE c.video_uuid = ?
                  AND (c.analysis_run_id IS NULL OR a.status = 'complete')
                ORDER BY c.suggested_start, c.created_at
                """,
                (str(video_uuid),),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _validate_candidate(candidate: CandidateCreate) -> None:
        if candidate.anchor_end <= candidate.anchor_start:
            raise ValueError("anchor_end must be greater than anchor_start")
        if candidate.suggested_end <= candidate.suggested_start:
            raise ValueError("suggested_end must be greater than suggested_start")

    def create_candidate(self, video_uuid: UUID, candidate: CandidateCreate) -> dict:
        self.ensure_video(video_uuid)
        self._validate_candidate(candidate)
        candidate_id = str(uuid4())
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO candidates(
                    candidate_id, video_uuid, analysis_run_id,
                    anchor_start, anchor_end, suggested_start, suggested_end,
                    canonical_transcript, category, analysis_reason,
                    status, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?, ?)
                """,
                (
                    candidate_id, str(video_uuid), candidate.anchor_start, candidate.anchor_end,
                    candidate.suggested_start, candidate.suggested_end,
                    candidate.canonical_transcript, candidate.category, candidate.analysis_reason,
                    now, now,
                ),
            )
            db.execute("UPDATE videos SET status = 'pending_review', updated_at = ? WHERE video_uuid = ?", (now, str(video_uuid)))
            return dict(db.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone())

    def create_analysis_candidate(
        self,
        video_uuid: UUID,
        analysis_run_id: str,
        lease_token: str,
        candidate: CandidateCreate,
    ) -> dict:
        self._validate_candidate(candidate)
        candidate_id = str(uuid4())
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT * FROM analysis_runs WHERE analysis_run_id = ? AND video_uuid = ?",
                (analysis_run_id, str(video_uuid)),
            ).fetchone()
            if not run:
                raise ValueError("analysis run not found")
            if not self._lease_matches(run, lease_token, now):
                raise ValueError("analysis worker lease is inactive")
            db.execute(
                """
                INSERT INTO candidates(
                    candidate_id, video_uuid, analysis_run_id,
                    anchor_start, anchor_end, suggested_start, suggested_end,
                    canonical_transcript, category, analysis_reason,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?, ?)
                """,
                (
                    candidate_id, str(video_uuid), analysis_run_id,
                    candidate.anchor_start, candidate.anchor_end,
                    candidate.suggested_start, candidate.suggested_end,
                    candidate.canonical_transcript, candidate.category, candidate.analysis_reason,
                    now, now,
                ),
            )
            return dict(db.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone())

    def review_candidate(self, video_uuid: UUID, candidate_id: str, review: CandidateReview) -> dict | None:
        now = self._iso(self._now())
        with self.connect() as db:
            current = db.execute(
                """
                SELECT c.*, a.status AS analysis_run_status
                FROM candidates c
                LEFT JOIN analysis_runs a ON a.analysis_run_id = c.analysis_run_id
                WHERE c.candidate_id = ? AND c.video_uuid = ?
                """,
                (candidate_id, str(video_uuid)),
            ).fetchone()
            if not current:
                return None
            if current["analysis_run_id"] is not None and current["analysis_run_status"] != "complete":
                raise ValueError("candidate belongs to an inactive analysis run")
            if (
                review.status in {"edited", "approved"}
                and review.editor_start is not None
                and review.editor_end is not None
                and review.editor_end <= review.editor_start
            ):
                raise ValueError("editor_end must be greater than editor_start")
            db.execute(
                """
                UPDATE candidates
                SET status = ?, editor_start = ?, editor_end = ?, acted_by_user_id = ?,
                    acted_at = ?, updated_at = ?
                WHERE candidate_id = ? AND video_uuid = ?
                """,
                (
                    review.status, review.editor_start, review.editor_end,
                    review.acted_by_user_id, now, now, candidate_id, str(video_uuid),
                ),
            )
            pending = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM candidates c
                LEFT JOIN analysis_runs a ON a.analysis_run_id = c.analysis_run_id
                WHERE c.video_uuid = ? AND c.status IN ('suggested', 'edited')
                  AND (c.analysis_run_id IS NULL OR a.status = 'complete')
                """,
                (str(video_uuid),),
            ).fetchone()["count"]
            video_status = "pending_review" if pending else "reviewed"
            db.execute("UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?", (video_status, now, str(video_uuid)))
            return dict(db.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone())

    def list_analysis_runs(self, video_uuid: UUID) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM analysis_runs WHERE video_uuid = ? ORDER BY created_at DESC, analysis_run_id DESC",
                (str(video_uuid),),
            ).fetchall()
            return [self._analysis_run_dict(row) for row in rows]

    def get_analysis_run(self, video_uuid: UUID, analysis_run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM analysis_runs WHERE video_uuid = ? AND analysis_run_id = ?",
                (str(video_uuid), analysis_run_id),
            ).fetchone()
            return self._analysis_run_dict(row)

    def claim_analysis_run(self, video_uuid: UUID, claim: AnalysisRunClaim) -> tuple[dict, bool]:
        self.ensure_video(video_uuid)
        now = self._iso(self._now())
        analysis_run_id = str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """
                SELECT * FROM analysis_runs
                WHERE video_uuid = ? AND caption_checksum = ? AND analyzer_version = ?
                LIMIT 1
                """,
                (str(video_uuid), claim.caption_checksum, claim.analyzer_version),
            ).fetchone()
            if existing:
                return self._analysis_run_dict(existing), False

            obsolete = db.execute(
                """
                SELECT analysis_run_id FROM analysis_runs
                WHERE video_uuid = ? AND status <> 'stale'
                  AND NOT (caption_checksum = ? AND analyzer_version = ?)
                """,
                (str(video_uuid), claim.caption_checksum, claim.analyzer_version),
            ).fetchall()
            obsolete_ids = [row["analysis_run_id"] for row in obsolete]
            if obsolete_ids:
                placeholders = ",".join("?" for _ in obsolete_ids)
                db.execute(
                    f"""
                    UPDATE analysis_runs
                    SET status = 'stale', worker_lease_token = NULL,
                        worker_lease_expires_at = NULL, updated_at = ?
                    WHERE analysis_run_id IN ({placeholders})
                    """,
                    (now, *obsolete_ids),
                )

            try:
                db.execute(
                    """
                    INSERT INTO analysis_runs(
                        analysis_run_id, video_uuid, caption_language, caption_checksum,
                        analyzer_version, model, prompt_version, status, error, caption_vtt,
                        worker_lease_token, worker_lease_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', NULL, NULL, NULL, NULL, ?, ?)
                    """,
                    (
                        analysis_run_id, str(video_uuid), claim.caption_language,
                        claim.caption_checksum, claim.analyzer_version, claim.model,
                        claim.prompt_version, now, now,
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
                return self._analysis_run_dict(existing), False
            db.execute("UPDATE videos SET status = 'ready_for_analysis', updated_at = ? WHERE video_uuid = ?", (now, str(video_uuid)))
            row = db.execute("SELECT * FROM analysis_runs WHERE analysis_run_id = ?", (analysis_run_id,)).fetchone()
            return self._analysis_run_dict(row), True

    def attach_caption_snapshot(self, video_uuid: UUID, analysis_run_id: str, caption_vtt: bytes) -> dict:
        if not caption_vtt:
            raise ValueError("caption snapshot is empty")
        if len(caption_vtt) > MAX_CAPTION_BYTES:
            raise ValueError("caption snapshot is too large")
        prefix = caption_vtt[:64].decode("utf-8", errors="replace")
        if not prefix.lstrip("\ufeff").lstrip().startswith("WEBVTT"):
            raise ValueError("caption snapshot is not WEBVTT")
        checksum = hashlib.sha256(caption_vtt).hexdigest()
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT * FROM analysis_runs WHERE video_uuid = ? AND analysis_run_id = ?",
                (str(video_uuid), analysis_run_id),
            ).fetchone()
            if not run:
                raise ValueError("analysis run not found")
            if run["status"] == "stale":
                raise ValueError("analysis run is stale")
            if checksum != run["caption_checksum"]:
                raise ValueError("caption snapshot checksum mismatch")
            db.execute(
                "UPDATE analysis_runs SET caption_vtt = ?, updated_at = ? WHERE video_uuid = ? AND analysis_run_id = ?",
                (caption_vtt, now, str(video_uuid), analysis_run_id),
            )
            row = db.execute("SELECT * FROM analysis_runs WHERE analysis_run_id = ?", (analysis_run_id,)).fetchone()
            return self._analysis_run_dict(row)

    def get_caption_snapshot(self, video_uuid: UUID, analysis_run_id: str) -> bytes | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT caption_vtt FROM analysis_runs WHERE video_uuid = ? AND analysis_run_id = ?",
                (str(video_uuid), analysis_run_id),
            ).fetchone()
            return None if not row or row["caption_vtt"] is None else bytes(row["caption_vtt"])

    def _recover_expired_leases(self, db: sqlite3.Connection, now: str) -> None:
        expired = db.execute(
            """
            SELECT analysis_run_id, video_uuid
            FROM analysis_runs
            WHERE status = 'analyzing' AND worker_lease_expires_at IS NOT NULL
              AND worker_lease_expires_at <= ?
            """,
            (now,),
        ).fetchall()
        for row in expired:
            db.execute("DELETE FROM candidates WHERE analysis_run_id = ?", (row["analysis_run_id"],))
            db.execute(
                """
                UPDATE analysis_runs
                SET status = 'queued', error = NULL, worker_lease_token = NULL,
                    worker_lease_expires_at = NULL, updated_at = ?
                WHERE analysis_run_id = ? AND status = 'analyzing'
                """,
                (now, row["analysis_run_id"]),
            )
            db.execute(
                "UPDATE videos SET status = 'ready_for_analysis', updated_at = ? WHERE video_uuid = ?",
                (now, row["video_uuid"]),
            )

    def claim_next_analysis_run(self) -> tuple[dict, str] | None:
        now_dt = self._now()
        now = self._iso(now_dt)
        expires = self._iso(now_dt + timedelta(seconds=WORKER_LEASE_SECONDS))
        lease_token = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_expired_leases(db, now)
            row = db.execute(
                """
                SELECT * FROM analysis_runs
                WHERE status = 'queued' AND caption_vtt IS NOT NULL
                ORDER BY created_at, analysis_run_id LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            cursor = db.execute(
                """
                UPDATE analysis_runs
                SET status = 'analyzing', error = NULL, worker_lease_token = ?,
                    worker_lease_expires_at = ?, updated_at = ?
                WHERE analysis_run_id = ? AND status = 'queued'
                """,
                (lease_token, expires, now, row["analysis_run_id"]),
            )
            if cursor.rowcount != 1:
                return None
            db.execute("UPDATE videos SET status = 'analyzing', updated_at = ? WHERE video_uuid = ?", (now, row["video_uuid"]))
            claimed = db.execute("SELECT * FROM analysis_runs WHERE analysis_run_id = ?", (row["analysis_run_id"],)).fetchone()
            return self._analysis_run_dict(claimed), lease_token

    def heartbeat_analysis_run(self, video_uuid: UUID, analysis_run_id: str, lease_token: str) -> dict:
        now_dt = self._now()
        now = self._iso(now_dt)
        expires = self._iso(now_dt + timedelta(seconds=WORKER_LEASE_SECONDS))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT * FROM analysis_runs WHERE video_uuid = ? AND analysis_run_id = ?",
                (str(video_uuid), analysis_run_id),
            ).fetchone()
            if not run:
                raise ValueError("analysis run not found")
            if not self._lease_matches(run, lease_token, now):
                raise ValueError("analysis worker lease is inactive")
            db.execute(
                "UPDATE analysis_runs SET worker_lease_expires_at = ?, updated_at = ? WHERE analysis_run_id = ?",
                (expires, now, analysis_run_id),
            )
            updated = db.execute("SELECT * FROM analysis_runs WHERE analysis_run_id = ?", (analysis_run_id,)).fetchone()
            return self._analysis_run_dict(updated)

    def finish_analysis_run(
        self,
        video_uuid: UUID,
        analysis_run_id: str,
        lease_token: str,
        update: AnalysisRunUpdate,
    ) -> dict:
        if update.status not in {"complete", "failed"}:
            raise ValueError("worker may only finish analysis as complete or failed")
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT * FROM analysis_runs WHERE video_uuid = ? AND analysis_run_id = ?",
                (str(video_uuid), analysis_run_id),
            ).fetchone()
            if not run:
                raise ValueError("analysis run not found")
            if not self._lease_matches(run, lease_token, now):
                raise ValueError("analysis worker lease is inactive")
            db.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error = ?, worker_lease_token = NULL,
                    worker_lease_expires_at = NULL, updated_at = ?
                WHERE analysis_run_id = ?
                """,
                (update.status, update.error, now, analysis_run_id),
            )
            if update.status == "failed":
                video_status = "partial_failure"
            else:
                count = db.execute(
                    "SELECT COUNT(*) AS count FROM candidates WHERE video_uuid = ? AND analysis_run_id = ?",
                    (str(video_uuid), analysis_run_id),
                ).fetchone()["count"]
                video_status = "pending_review" if count else "reviewed"
            db.execute("UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?", (video_status, now, str(video_uuid)))
            updated = db.execute("SELECT * FROM analysis_runs WHERE analysis_run_id = ?", (analysis_run_id,)).fetchone()
            return self._analysis_run_dict(updated)

    def update_analysis_run(self, video_uuid: UUID, analysis_run_id: str, update: AnalysisRunUpdate) -> dict | None:
        now = self._iso(self._now())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT * FROM analysis_runs WHERE analysis_run_id = ? AND video_uuid = ?",
                (analysis_run_id, str(video_uuid)),
            ).fetchone()
            if not current:
                return None
            current_status = current["status"]
            allowed = {
                "queued": {"queued", "analyzing", "failed", "stale"},
                "analyzing": {"analyzing", "complete", "failed", "stale"},
                "complete": {"complete", "stale"},
                "failed": {"failed", "stale"},
                "stale": {"stale"},
            }
            if update.status not in allowed.get(current_status, set()):
                raise ValueError(f"invalid analysis transition: {current_status} -> {update.status}")
            clear_lease = update.status in {"complete", "failed", "stale"}
            db.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error = ?,
                    worker_lease_token = CASE WHEN ? THEN NULL ELSE worker_lease_token END,
                    worker_lease_expires_at = CASE WHEN ? THEN NULL ELSE worker_lease_expires_at END,
                    updated_at = ?
                WHERE analysis_run_id = ? AND video_uuid = ?
                """,
                (update.status, update.error, clear_lease, clear_lease, now, analysis_run_id, str(video_uuid)),
            )
            if update.status == "queued":
                video_status = "ready_for_analysis"
            elif update.status == "analyzing":
                video_status = "analyzing"
            elif update.status == "failed":
                video_status = "partial_failure"
            elif update.status == "complete":
                count = db.execute(
                    "SELECT COUNT(*) AS count FROM candidates WHERE video_uuid = ? AND analysis_run_id = ?",
                    (str(video_uuid), analysis_run_id),
                ).fetchone()["count"]
                video_status = "pending_review" if count else "reviewed"
            else:
                video_status = None
            if video_status:
                db.execute("UPDATE videos SET status = ?, updated_at = ? WHERE video_uuid = ?", (video_status, now, str(video_uuid)))
            row = db.execute("SELECT * FROM analysis_runs WHERE analysis_run_id = ?", (analysis_run_id,)).fetchone()
            return self._analysis_run_dict(row)
