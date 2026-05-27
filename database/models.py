from datetime import datetime, UTC

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskModel(Base):
    __tablename__ = "tasks"


    task_id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    input: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    artifacts: Mapped[list["ArtifactModel"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )


class ArtifactModel(Base):
    __tablename__ = "artifacts"


    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id"),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    agent_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    task: Mapped["TaskModel"] = relationship(
        back_populates="artifacts",
    )