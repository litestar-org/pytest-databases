from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.docker.redis import redis_responsive
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator

COMPOSE_PROJECT_NAME: str = f"pytest-databases-dragonfly-{simple_string_hash(__file__)}"


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
def dragonfly_service(
    dragonfly_docker_services: DockerServiceRegistry,
    default_dragonfly_service_name: str,
    dragonfly_docker_compose_files: list[Path],
    dragonfly_port: int,
) -> Generator[None, None, None]:
    os.environ["DRAGONFLY_PORT"] = str(dragonfly_port)
    dragonfly_docker_services.start(
        name=default_dragonfly_service_name,
        docker_compose_files=dragonfly_docker_compose_files,
        check=redis_responsive,
        port=dragonfly_port,
    )
    yield
