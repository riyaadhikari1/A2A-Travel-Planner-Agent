from fastapi import HTTPException


class TaskNotFoundException(HTTPException):
    def __init__(self, task_id: str):
        super().__init__(
            status_code=404,
            detail=f"Task with id '{task_id}' not found.",
        )


class AgentUnavailableException(HTTPException):
    def __init__(self, agent_name: str):
        super().__init__(
            status_code=503,
            detail=f"Agent '{agent_name}' is unavailable.",
        )


class AgentExecutionException(HTTPException):
    def __init__(self, agent_name: str, message: str):
        super().__init__(
            status_code=500,
            detail=f"Execution failed for agent '{agent_name}': {message}",
        )


class InvalidTaskStateException(HTTPException):
    def __init__(
        self,
        task_id: str,
        current_status: str,
        attempted_status: str,
    ):
        super().__init__(
            status_code=409,
            detail=(
                f"Invalid task state transition for task '{task_id}'. "
                f"Current status: '{current_status}', "
                f"Attempted status: '{attempted_status}'."
            ),
        )


class OrchestratorException(HTTPException):
    def __init__(self, reason: str):
        super().__init__(
            status_code=500,
            detail=f"Orchestrator error: {reason}",
        )


class CORSViolationException(Exception):
    def __init__(self, origin: str):
        self.origin = origin
        self.detail = f"CORS violation: Origin '{origin}' is not allowed."
        super().__init__(self.detail)