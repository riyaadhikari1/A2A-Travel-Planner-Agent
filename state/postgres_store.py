from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from database.models import ArtifactModel, TaskModel
from shared.logging import get_logger
from shared.schemas.artifact import Artifact
from shared.schemas.exceptions import TaskNotFoundException
from shared.schemas.task import TaskRecord

logger = get_logger(__name__)


class PostgresStore:

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save_completed(self, task_record: TaskRecord) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                session.add(TaskModel(
                    task_id=task_record.task_id,
                    status=task_record.status,
                    input=task_record.input,
                    created_at=task_record.created_at,
                    updated_at=task_record.updated_at,
                ))
                for artifact in task_record.artifacts:
                    session.add(ArtifactModel(
                        task_id=task_record.task_id,
                        type=artifact.artifact_type,
                        agent_name=artifact.agent_name,
                        payload=artifact.payload,
                        created_at=artifact.created_at,
                    ))
                logger.info("Persisted completed task %s", task_record.task_id)

    async def get(self, task_id: str) -> TaskRecord:
        async with self.session_factory() as session:
            result = await session.execute(
                select(TaskModel)
                .options(selectinload(TaskModel.artifacts))
                .where(TaskModel.task_id == task_id)
            )
            task_model = result.scalar_one_or_none()
            if task_model is None:
                raise TaskNotFoundException(task_id)
            return TaskRecord(
                task_id=task_model.task_id,
                status=task_model.status,
                input=task_model.input,
                created_at=task_model.created_at,
                updated_at=task_model.updated_at,
                artifacts=[
                    Artifact(
                        artifact_type=a.type,
                        agent_name=a.agent_name,
                        payload=a.payload,
                        created_at=a.created_at,
                    )
                    for a in task_model.artifacts
                ],
            )