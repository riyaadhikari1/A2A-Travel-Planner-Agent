import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import AgentCard

from shared.config import config_manager
from shared.logging import get_logger
from shared.schemas.exceptions import AgentUnavailableException

logger = get_logger(__name__)


class AgentRegistry:

    def __init__(self) -> None:
        self._cards:    dict[str, AgentCard] = {}
        self._urls:     dict[str, str]       = {}
        self._http:     httpx.AsyncClient    = httpx.AsyncClient(timeout=10.0)
        self._expected: int                  = 0

    async def resolve_all(self) -> None:
        agents_config = config_manager.load("agents")["agents"]
        agent_urls: dict[str, str] = {
            name: agent["url"]
            for name, agent in agents_config.items()
        }
        self._expected = len(agent_urls)

        for name, url in agent_urls.items():
            try:
                resolver = A2ACardResolver(
                    httpx_client=self._http,
                    base_url=url,
                )
                card = await resolver.get_agent_card()
                self._cards[name] = card
                self._urls[name]  = url
                logger.info(
                    "Resolved agent '%s' -> %s (card: %s)",
                    name, url, card.name,
                )
            except Exception as e:
                logger.error(
                    "Failed to resolve agent '%s' at %s: %s",
                    name, url, e,
                )

        logger.info(
            "Registry ready: %d/%d agents resolved: %s",
            len(self._urls),
            self._expected,
            list(self._urls.keys()),
        )

    def get_endpoint(self, name: str) -> str:
        url = self._urls.get(name)
        if not url:
            raise AgentUnavailableException(name)
        return url

    def get_card(self, name: str) -> AgentCard | None:
        return self._cards.get(name)

    def get_all(self) -> list[dict]:
        result = []
        for name, url in self._urls.items():
            card = self._cards.get(name)
            result.append({
                "name":        name,
                "url":         url,
                "agent_name":  card.name        if card else name,
                "description": card.description if card else "",
                "skills":      list(card.skills) if card else [],
            })
        return result

    def all_healthy(self) -> bool:
        return len(self._urls) == self._expected

    async def close(self) -> None:
        await self._http.aclose()