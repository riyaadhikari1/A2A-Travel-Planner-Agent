import asyncio
import uvicorn
import httpx

from agents.weather_agent.forecast         import create_weather_app
from agents.domestic_flight_agent.search   import create_domestic_flight_app
from agents.intl_flight_agent.search       import create_intl_flight_app
from agents.hotel_agent.search             import create_hotel_app
from agents.budget_agent.estimate          import create_budget_app
from gateway.app                           import app as gateway_app
from shared.config                         import settings
from shared.logging                        import get_logger

logger = get_logger("main")

AGENTS = [
    ("weather",         settings.weather_agent_port,         create_weather_app),
    ("domestic_flight", settings.domestic_flight_agent_port, create_domestic_flight_app),
    ("intl_flight",     settings.intl_flight_agent_port,     create_intl_flight_app),
    ("hotel",           settings.hotel_agent_port,           create_hotel_app),
    ("budget",          settings.budget_agent_port,          create_budget_app),
]

HEALTH_CHECK_ATTEMPTS = 15
HEALTH_CHECK_INTERVAL = 1.0
AGENT_BOOT_WAIT       = 2.0


def make_config(app, port: int, lifespan: str = "off") -> uvicorn.Config:
    return uvicorn.Config(
        app=app,
        host=settings.host,
        port=port,
        log_level=settings.log_level.lower(),
        lifespan=lifespan,
    )


async def wait_for_agents() -> bool:
    logger.info("Waiting %.1fs for agents to boot...", AGENT_BOOT_WAIT)
    await asyncio.sleep(AGENT_BOOT_WAIT)

    agent_urls = {
        name: f"http://localhost:{port}"
        for name, port, _ in AGENTS
    }

    healthy: set[str] = set()

    async with httpx.AsyncClient(timeout=3.0) as client:
        for attempt in range(1, HEALTH_CHECK_ATTEMPTS + 1):
            for name, url in agent_urls.items():
                if name in healthy:
                    continue
                try:
                    resp = await client.get(f"{url}/health")
                    if resp.status_code == 200:
                        healthy.add(name)
                        logger.info("Agent '%s' healthy.", name)
                except Exception:
                    pass

            if len(healthy) == len(agent_urls):
                logger.info("All %d agents healthy.", len(healthy))
                return True

            missing = set(agent_urls.keys()) - healthy
            logger.debug(
                "Health check attempt %d/%d — waiting for: %s",
                attempt, HEALTH_CHECK_ATTEMPTS, missing,
            )
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    missing = set(agent_urls.keys()) - healthy
    logger.warning(
        "Gateway starting with %d/%d agents healthy. Missing: %s",
        len(healthy), len(agent_urls), missing,
    )
    return False


async def main() -> None:
    agent_configs = [
        make_config(factory(), port)
        for _, port, factory in AGENTS
    ]
    agent_servers = [uvicorn.Server(cfg) for cfg in agent_configs]
    for s in agent_servers:
        s.install_signal_handlers = False

    for name, port, _ in AGENTS:
        logger.info("Starting agent '%s' on port %d", name, port)

    agent_tasks = [
        asyncio.create_task(server.serve())
        for server in agent_servers
    ]

    await wait_for_agents()

    gateway_config = make_config(
        gateway_app,
        settings.gateway_port,
        lifespan="on",
    )
    gateway_server = uvicorn.Server(gateway_config)
    gateway_server.install_signal_handlers = False

    logger.info("Starting gateway on port %d", settings.gateway_port)

    await gateway_server.serve()

    for task in agent_tasks:
        task.cancel()
    await asyncio.gather(*agent_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())