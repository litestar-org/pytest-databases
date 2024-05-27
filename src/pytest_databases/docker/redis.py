from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-redis-{simple_string_hash(__file__)}"


async def redis_responsive(host: str, port: int) -> bool:
    client: AsyncRedis = AsyncRedis(host=host, port=port)
    try:
        return await client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        await client.aclose()  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def redis_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def redis_docker_services(
    redis_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=redis_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def redis_port() -> int:
    return 6397


@pytest.fixture(scope="session")
def redis_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.redis.yml")]


@pytest.fixture(scope="session")
def default_redis_service_name() -> str:
    return "redis"


@pytest.fixture(scope="session")
def redis_docker_ip(redis_docker_services: DockerServiceRegistry) -> str:
    return redis_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def redis_service(
    redis_docker_services: DockerServiceRegistry,
    default_redis_service_name: str,
    redis_docker_compose_files: list[Path],
    redis_port: int,
) -> AsyncGenerator[None, None]:
    os.environ["REDIS_PORT"] = str(redis_port)
    await redis_docker_services.start(
        name=default_redis_service_name,
        docker_compose_files=redis_docker_compose_files,
        check=redis_responsive,
        port=redis_port,
    )
    yield
