# MIT License

# Copyright (c) 2024 Litestar

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


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

COMPOSE_PROJECT_NAME: str = f"pytest-databases-dragonfly-{simple_string_hash(__file__)}"


async def dragonfly_responsive(host: str, port: int) -> bool:
    client: AsyncRedis = AsyncRedis(host=host, port=port)
    try:
        return await client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        await client.aclose()  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def dragonfly_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def dragonfly_docker_services(
    dragonfly_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=dragonfly_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def dragonfly_port() -> int:
    return 6398


@pytest.fixture(scope="session")
def dragonfly_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.dragonfly.yml")]


@pytest.fixture(scope="session")
def default_dragonfly_service_name() -> str:
    return "dragonfly"


@pytest.fixture(scope="session")
def dragonfly_docker_ip(dragonfly_docker_services: DockerServiceRegistry) -> str:
    return dragonfly_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def dragonfly_service(
    dragonfly_docker_services: DockerServiceRegistry,
    default_dragonfly_service_name: str,
    dragonfly_docker_compose_files: list[Path],
    dragonfly_port: int,
) -> AsyncGenerator[None, None]:
    os.environ["DRAGONFLY_PORT"] = str(dragonfly_port)
    await dragonfly_docker_services.start(
        name=default_dragonfly_service_name,
        docker_compose_files=dragonfly_docker_compose_files,
        check=dragonfly_responsive,
        port=dragonfly_port,
    )
    yield
