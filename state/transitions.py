from shared.schemas.task import TaskStatus

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED:  {TaskStatus.RUNNING},
    TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
}