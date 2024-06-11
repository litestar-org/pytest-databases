from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from google.auth.credentials import AnonymousCredentials, Credentials
from google.cloud import spanner

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-spanner-{simple_string_hash(__file__)}"


def spanner_responsive(
    host: str,
    spanner_port: int,
    spanner_instance: str,
    spanner_database: str,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> bool:
    try:
        spanner_client = spanner.Client(project=spanner_project, credentials=spanner_credentials)
        instance = spanner_client.instance(spanner_instance)
        with contextlib.suppress(Exception):
            instance.create()

        database = instance.database(spanner_database)
        with contextlib.suppress(Exception):
            database.create()

        with database.snapshot() as snapshot:
            resp = next(iter(snapshot.execute_sql("SELECT 1")))
        return resp[0] == 1
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def spanner_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def spanner_docker_services(
    spanner_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=spanner_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def spanner_port() -> int:
    return 9010


@pytest.fixture(scope="session")
def spanner_instance() -> str:
    return "test-instance"


@pytest.fixture(scope="session")
def spanner_database() -> str:
    return "test-database"


@pytest.fixture(scope="session")
def spanner_project() -> str:
    return "emulator-test-project"


@pytest.fixture(scope="session")
def spanner_credentials() -> Credentials:
    return AnonymousCredentials()


@pytest.fixture(scope="session")
def spanner_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.spanner.yml")]


@pytest.fixture(scope="session")
def default_spanner_service_name() -> str:
    return "spanner"


@pytest.fixture(scope="session")
def spanner_docker_ip(spanner_docker_services: DockerServiceRegistry) -> str:
    return spanner_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def spanner_service(
    spanner_docker_services: DockerServiceRegistry,
    default_spanner_service_name: str,
    spanner_docker_compose_files: list[Path],
    spanner_docker_ip: str,
    spanner_port: int,
    spanner_instance: str,
    spanner_database: str,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> AsyncGenerator[None, None]:
    os.environ["SPANNER_EMULATOR_HOST"] = f"{spanner_docker_ip}:{spanner_port}"
    os.environ["SPANNER_DATABASE"] = spanner_database
    os.environ["SPANNER_INSTANCE"] = spanner_instance
    os.environ["SPANNER_PORT"] = str(spanner_port)
    os.environ["GOOGLE_CLOUD_PROJECT"] = spanner_project
    await spanner_docker_services.start(
        name=default_spanner_service_name,
        docker_compose_files=spanner_docker_compose_files,
        timeout=60,
        check=spanner_responsive,
        spanner_port=spanner_port,
        spanner_instance=spanner_instance,
        spanner_database=spanner_database,
        spanner_project=spanner_project,
        spanner_credentials=spanner_credentials,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def spanner_startup_connection(
    spanner_service: DockerServiceRegistry,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> AsyncGenerator[spanner.Client, None]:
    c = spanner.Client(project=spanner_project, credentials=spanner_credentials)
    yield c
