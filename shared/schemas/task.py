from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.artifact import Artifact


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: TaskStatus
    input: str
    artifacts: list[Artifact] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    instruction: str


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    artifact: Artifact
    duration_ms: int = 0