"""SQLite persistence for redacted workflow-run checkpoints."""

import json
import sqlite3
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.domain.workflow import WorkflowRunSnapshot
from app.tools.workflow_runs import WorkflowRunStoreError

SQLITE_URL_PREFIX = "sqlite:///"


def sqlite_path(database_url: str) -> Path:
    """Resolve the configured application SQLite path."""

    if not database_url.startswith(SQLITE_URL_PREFIX):
        raise WorkflowRunStoreError("unsupported workflow database URL")
    raw_path = database_url.removeprefix(SQLITE_URL_PREFIX)
    if not raw_path:
        raise WorkflowRunStoreError("workflow database path is empty")
    return Path(raw_path)


class SqliteWorkflowRunStore:
    """Persist one redacted JSON checkpoint per workflow run."""

    def __init__(self, database_url: str) -> None:
        self._path = sqlite_path(database_url)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_runs (
                        workflow_id TEXT PRIMARY KEY,
                        correlation_id TEXT NOT NULL,
                        trace_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        review_version INTEGER NOT NULL DEFAULT 0,
                        snapshot_json TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(workflow_runs)")
                }
                if "review_version" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE workflow_runs
                        ADD COLUMN review_version INTEGER NOT NULL DEFAULT 0
                        """
                    )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
                    ON workflow_runs(status)
                    """
                )
        except (OSError, sqlite3.Error) as error:
            raise WorkflowRunStoreError(
                "workflow storage initialization failed"
            ) from error

    async def initialize(self) -> None:
        """Create the workflow-run table and status index."""

        self._initialize()

    def _save(self, snapshot: WorkflowRunSnapshot) -> None:
        payload = json.dumps(
            snapshot.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO workflow_runs (
                        workflow_id,
                        correlation_id,
                        trace_id,
                        status,
                        created_at,
                        updated_at,
                        review_version,
                        snapshot_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        correlation_id = excluded.correlation_id,
                        trace_id = excluded.trace_id,
                        status = excluded.status,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        review_version = excluded.review_version,
                        snapshot_json = excluded.snapshot_json
                    """,
                    (
                        str(snapshot.workflow_id),
                        str(snapshot.correlation_id),
                        str(snapshot.trace_id),
                        snapshot.status.value,
                        snapshot.created_at.isoformat(),
                        snapshot.updated_at.isoformat(),
                        snapshot.review_version,
                        payload,
                    ),
                )
        except (OSError, sqlite3.Error) as error:
            raise WorkflowRunStoreError("workflow checkpoint write failed") from error

    async def save(self, snapshot: WorkflowRunSnapshot) -> None:
        """Insert or replace one redacted checkpoint."""

        self._save(snapshot)

    @staticmethod
    def _parse_snapshot(payload: str) -> WorkflowRunSnapshot:
        try:
            decoded = json.loads(payload)
            return WorkflowRunSnapshot.model_validate(decoded)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise WorkflowRunStoreError("workflow checkpoint is invalid") from error

    def _get(self, workflow_id: UUID) -> WorkflowRunSnapshot | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT snapshot_json
                    FROM workflow_runs
                    WHERE workflow_id = ?
                    """,
                    (str(workflow_id),),
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            raise WorkflowRunStoreError("workflow checkpoint read failed") from error
        if row is None:
            return None
        return self._parse_snapshot(str(row["snapshot_json"]))

    async def get(self, workflow_id: UUID) -> WorkflowRunSnapshot | None:
        """Return one validated checkpoint."""

        return self._get(workflow_id)

    def _list_pending_review(self) -> list[WorkflowRunSnapshot]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT snapshot_json
                    FROM workflow_runs
                    WHERE status = 'pending_review'
                    ORDER BY updated_at, workflow_id
                    """
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise WorkflowRunStoreError("workflow review queue read failed") from error
        return [self._parse_snapshot(str(row["snapshot_json"])) for row in rows]

    async def list_pending_review(self) -> list[WorkflowRunSnapshot]:
        """Return pending-review checkpoints in deterministic order."""

        return self._list_pending_review()

    def _save_if_review_version(
        self,
        snapshot: WorkflowRunSnapshot,
        *,
        expected_review_version: int,
    ) -> bool:
        payload = json.dumps(
            snapshot.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE workflow_runs
                    SET
                        correlation_id = ?,
                        trace_id = ?,
                        status = ?,
                        created_at = ?,
                        updated_at = ?,
                        review_version = ?,
                        snapshot_json = ?
                    WHERE workflow_id = ?
                    AND status = 'pending_review'
                    AND review_version = ?
                    """,
                    (
                        str(snapshot.correlation_id),
                        str(snapshot.trace_id),
                        snapshot.status.value,
                        snapshot.created_at.isoformat(),
                        snapshot.updated_at.isoformat(),
                        snapshot.review_version,
                        payload,
                        str(snapshot.workflow_id),
                        expected_review_version,
                    ),
                )
        except (OSError, sqlite3.Error) as error:
            raise WorkflowRunStoreError(
                "workflow review action write failed"
            ) from error
        return cursor.rowcount == 1

    async def save_if_review_version(
        self,
        snapshot: WorkflowRunSnapshot,
        *,
        expected_review_version: int,
    ) -> bool:
        """Save a reviewed checkpoint only if its review version is current."""

        return self._save_if_review_version(
            snapshot,
            expected_review_version=expected_review_version,
        )

    def _list_incomplete(self) -> list[WorkflowRunSnapshot]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT snapshot_json
                    FROM workflow_runs
                    WHERE status IN ('queued', 'running')
                    ORDER BY created_at, workflow_id
                    """
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            raise WorkflowRunStoreError("workflow recovery read failed") from error
        return [self._parse_snapshot(str(row["snapshot_json"])) for row in rows]

    async def list_incomplete(self) -> list[WorkflowRunSnapshot]:
        """Return incomplete checkpoints in deterministic order."""

        return self._list_incomplete()
