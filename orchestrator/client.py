import asyncio
import json
import uuid

import httpx
from google.protobuf.json_format import MessageToDict

from a2a.client.client_factory import create_client
from a2a.client.client import ClientConfig
from a2a.types import (
    SendMessageRequest,
    Message,
    Part,
    Role,
)

from shared.config import settings
from shared.logging import get_logger
from shared.schemas.artifact import Artifact
from shared.schemas.exceptions import AgentExecutionException, AgentUnavailableException
from shared.schemas.task import AgentRequest, AgentResponse

logger = get_logger(__name__)


class OrchestratorClient:
    """
    Sends A2A requests to agent servers using the official SDK client.

    A fresh httpx.AsyncClient is created per call so that parallel agent
    calls never share connection pool state, avoiding cross-call interference
    regardless of OS or event loop implementation.
    """

    def __init__(self) -> None:
        self.timeout = settings.default_timeout

    async def call_agent(
        self,
        name: str,
        endpoint: str,
        request: AgentRequest,
    ) -> AgentResponse:

        logger.info(
            "Calling agent '%s' at %s -- instruction: %.80s",
            name, endpoint, request.instruction,
        )

        try:
            start = asyncio.get_event_loop().time()

            message_id = str(uuid.uuid4())

            part = Part()
            part.text = request.instruction

            message = Message()
            message.message_id = message_id
            message.role = Role.Value("ROLE_USER")
            message.parts.append(part)

            send_request = SendMessageRequest()
            send_request.message.CopyFrom(message)

            async with httpx.AsyncClient(timeout=self.timeout) as http_client:
                config = ClientConfig(
                    streaming=True,
                    httpx_client=http_client,
                )
                client = await create_client(
                    agent=endpoint,
                    client_config=config,
                )

                artifact_payload: dict = {}

                async for stream_response in client.send_message(send_request):
                    response_dict = MessageToDict(
                        stream_response,
                        preserving_proto_field_name=False,
                    )

                    artifact_update = response_dict.get("artifactUpdate")
                    if artifact_update:
                        artifact = artifact_update.get("artifact", {})
                        for part_dict in artifact.get("parts", []):
                            data = part_dict.get("data")
                            if data is not None:
                                if isinstance(data, dict):
                                    artifact_payload = data
                                else:
                                    try:
                                        artifact_payload = json.loads(str(data))
                                    except Exception:
                                        pass
                                break

                    status_update = response_dict.get("statusUpdate")
                    if status_update:
                        state = (
                            status_update
                            .get("status", {})
                            .get("state", "")
                        )
                        logger.debug("Agent '%s' state: %s", name, state)
                        if state in (
                            "TASK_STATE_COMPLETED",
                            "TASK_STATE_FAILED",
                            "TASK_STATE_CANCELED",
                            "TASK_STATE_REJECTED",
                        ):
                            break

                await client.close()

            duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)

            if artifact_payload:
                logger.info(
                    "Agent '%s' completed in %dms -- %d payload keys.",
                    name, duration_ms, len(artifact_payload),
                )
            else:
                logger.warning(
                    "Agent '%s' completed in %dms but returned no artifact payload.",
                    name, duration_ms,
                )

            artifact = Artifact(
                artifact_type=name,   # validator handles coercion
                agent_name=name,
                payload=artifact_payload or {},
)

            return AgentResponse(
                agent_name=name,
                artifact=artifact,
                duration_ms=duration_ms,
            )

        except httpx.ConnectError:
            logger.error("Agent '%s' unreachable at %s", name, endpoint)
            raise AgentUnavailableException(name)
        except httpx.TimeoutException:
            logger.error("Agent '%s' timed out", name)
            raise AgentUnavailableException(name)
        except httpx.HTTPStatusError as e:
            logger.error("Agent '%s' returned HTTP %s", name, e.response.status_code)
            raise AgentExecutionException(name, str(e))
        except (AgentUnavailableException, AgentExecutionException):
            raise
        except Exception as e:
            logger.error("Agent '%s' unexpected error: %s", name, e)
            raise AgentExecutionException(name, str(e))