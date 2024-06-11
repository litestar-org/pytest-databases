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


COMPOSE_PROJECT_NAME: str = f"pytest-databases-valkey-{simple_string_hash(__file__)}"


async def valkey_responsive(host: str, port: int) -> bool:
    client: AsyncRedis = AsyncRedis(host=host, port=port)
    try:
        return await client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        await client.aclose()  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def valkey_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def valkey_docker_services(
    valkey_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=valkey_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def valkey_port() -> int:
    return 6308


@pytest.fixture(scope="session")
def valkey_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.valkey.yml")]


@pytest.fixture(scope="session")
def default_valkey_service_name() -> str:
    return "valkey"


@pytest.fixture(scope="session")
def valkey_docker_ip(valkey_docker_services: DockerServiceRegistry) -> str:
    return valkey_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def valkey_service(
    valkey_docker_services: DockerServiceRegistry,
    default_valkey_service_name: str,
    valkey_docker_compose_files: list[Path],
    valkey_port: int,
) -> AsyncGenerator[None, None]:
    os.environ["REDIS_PORT"] = str(valkey_port)
    await valkey_docker_services.start(
        name=default_valkey_service_name,
        docker_compose_files=valkey_docker_compose_files,
        check=valkey_responsive,
        port=valkey_port,
    )
    yield
