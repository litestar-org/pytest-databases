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


COMPOSE_PROJECT_NAME: str = f"pytest-databases-keydb-{simple_string_hash(__file__)}"


async def keydb_responsive(host: str, port: int) -> bool:
    client: AsyncRedis = AsyncRedis(host=host, port=port)
    try:
        return await client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        await client.aclose()  # type: ignore[attr-defined]


@pytest.fixture(autouse=False, scope="session")
def keydb_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(scope="session")
def keydb_docker_services(
    keydb_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=keydb_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def keydb_port() -> int:
    return 6396


@pytest.fixture(scope="session")
def keydb_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.keydb.yml")]


@pytest.fixture(scope="session")
def default_keydb_service_name() -> str:
    return "keydb"


@pytest.fixture(scope="session")
def keydb_docker_ip(keydb_docker_services: DockerServiceRegistry) -> str:
    return keydb_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def keydb_service(
    keydb_docker_services: DockerServiceRegistry,
    default_keydb_service_name: str,
    keydb_docker_compose_files: list[Path],
    keydb_port: int,
) -> AsyncGenerator[None, None]:
    os.environ["KEYDB_PORT"] = str(keydb_port)
    await keydb_docker_services.start(
        name=default_keydb_service_name,
        docker_compose_files=keydb_docker_compose_files,
        check=keydb_responsive,
        port=keydb_port,
    )
    yield
