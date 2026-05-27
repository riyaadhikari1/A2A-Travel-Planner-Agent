import asyncio
import json

from openai import AsyncOpenAI

from orchestrator.client import OrchestratorClient
from orchestrator.registry import AgentRegistry
from shared.config import config_manager, settings
from shared.logging import get_logger
from shared.schemas.exceptions import AgentUnavailableException
from shared.schemas.task import AgentRequest, AgentResponse, TaskRecord

logger = get_logger(__name__)

CLARIFICATION_NEEDED = "clarification_needed"


class Planner:

    def __init__(
        self,
        client: OrchestratorClient,
        registry: AgentRegistry,
    ) -> None:
        self.client         = client
        self.registry       = registry
        self.system_prompt  = config_manager.load("planner_system")["system"]
        self.routing_prompt = config_manager.load("planner_routing")["routing"]
        self._llm           = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.openrouter_base_url,
        )

    async def plan(
        self,
        task_record: TaskRecord,
    ) -> list[AgentResponse] | str:

        logger.info("Planning task %s.", task_record.task_id)

        prompt = self.routing_prompt.format(user_input=task_record.input)

        response = await self._llm.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user",   "content": prompt},
            ],
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
        raw = response.choices[0].message.content.strip()
        logger.debug("Planner raw response: %s", raw)

        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            if start == -1 or end == 0:
                logger.warning(
                    "Task %s — planner returned unparseable response: %.120s",
                    task_record.task_id, raw,
                )
                return CLARIFICATION_NEEDED
            try:
                plan = json.loads(raw[start:end])
            except json.JSONDecodeError:
                logger.warning(
                    "Task %s — planner JSON extraction failed: %.120s",
                    task_record.task_id, raw,
                )
                return CLARIFICATION_NEEDED

        if not plan:
            logger.info(
                "Task %s — planner returned empty plan, clarification needed.",
                task_record.task_id,
            )
            return CLARIFICATION_NEEDED

        logger.info(
            "Task %s — plan: %d steps: %s",
            task_record.task_id,
            len(plan),
            [p["agent"] for p in plan],
        )

        non_budget  = [p for p in plan if p["agent"] != "budget"]
        budget_step = next((p for p in plan if p["agent"] == "budget"), None)

        agent_tasks = []
        for step in non_budget:
            try:
                endpoint = self.registry.get_endpoint(step["agent"])
            except AgentUnavailableException:
                logger.warning(
                    "Agent '%s' not in registry, skipping.",
                    step["agent"],
                )
                continue

            agent_tasks.append(
                self.client.call_agent(
                    step["agent"],
                    endpoint,
                    AgentRequest(
                        task_id=task_record.task_id,
                        instruction=step["instruction"],
                    ),
                )
            )

        if not agent_tasks:
            logger.warning(
                "Task %s — no callable agents in plan, clarification needed.",
                task_record.task_id,
            )
            return CLARIFICATION_NEEDED

        logger.info(
            "Task %s — dispatching %d agents in parallel.",
            task_record.task_id, len(agent_tasks),
        )

        loop    = asyncio.get_running_loop()
        start   = loop.time()
        results = await asyncio.gather(*agent_tasks, return_exceptions=True)
        elapsed = int((loop.time() - start) * 1000)

        responses: list[AgentResponse] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Agent call failed: %s", result)
            else:
                responses.append(result)

        if not responses:
            logger.warning(
                "Task %s — all agent calls failed, clarification needed.",
                task_record.task_id,
            )
            return CLARIFICATION_NEEDED

        logger.info(
            "Task %s — %d/%d agents succeeded in %dms.",
            task_record.task_id,
            len(responses),
            len(agent_tasks),
            elapsed,
        )

        if budget_step and responses:
            combined = {
                r.artifact.artifact_type: r.artifact.payload
                for r in responses
            }
            budget_instruction = (
                f"Estimate budget for trip with the following data: "
                f"{json.dumps(combined)}"
            )
            try:
                endpoint = self.registry.get_endpoint("budget")
                budget_response = await self.client.call_agent(
                    "budget",
                    endpoint,
                    AgentRequest(
                        task_id=task_record.task_id,
                        instruction=budget_instruction,
                    ),
                )
                responses.append(budget_response)
            except Exception as e:
                logger.error("Budget agent failed: %s", e)

        return responses