"""Application-owned workflow-run persistence capability."""

from typing import Protocol
from uuid import UUID

from app.domain.workflow import WorkflowRunSnapshot


class WorkflowRunStoreError(RuntimeError):
    """A workflow checkpoint could not be stored or read safely."""


class WorkflowRunStore(Protocol):
    """Persist redacted workflow checkpoints without clinical input data."""

    async def initialize(self) -> None:
        """Create or validate application-owned storage."""

    async def save(self, snapshot: WorkflowRunSnapshot) -> None:
        """Insert or replace one workflow checkpoint."""

    async def get(self, workflow_id: UUID) -> WorkflowRunSnapshot | None:
        """Return one checkpoint or None when it does not exist."""

    async def list_pending_review(self) -> list[WorkflowRunSnapshot]:
        """Return pending-review checkpoints in deterministic order."""

    async def save_if_review_version(
        self,
        snapshot: WorkflowRunSnapshot,
        *,
        expected_review_version: int,
    ) -> bool:
        """Save a reviewed checkpoint only if its review version is current."""

    async def list_incomplete(self) -> list[WorkflowRunSnapshot]:
        """Return queued and running checkpoints for safe recovery."""
