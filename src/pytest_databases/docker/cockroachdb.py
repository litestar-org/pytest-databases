from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import psycopg
import pytest
from psycopg.connection_async import AsyncConnection

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator

    from psycopg.rows import TupleRow


COMPOSE_PROJECT_NAME: str = f"pytest-databases-cockroachdb-{simple_string_hash(__file__)}"


async def cockroachdb_responsive(host: str, port: int, database: str, driver_opts: dict[str, str]) -> bool:
    opts = "&".join(f"{k}={v}" for k, v in driver_opts.items()) if driver_opts else ""
    try:
        with psycopg.connect(f"cockroachdbql://root@{host}:{port}/{database}?{opts}") as conn, conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] if resp is not None else 0 == 1  # noqa: PLR0133
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def cockroachdb_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def cockroachdb_docker_services(
    cockroachdb_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=cockroachdb_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def cockroachdb_port() -> int:
    return 26257


@pytest.fixture(scope="session")
def cockroachdb_database() -> str:
    return "defaultdb"


@pytest.fixture(scope="session")
def cockroachdb_driver_opts() -> dict[str, str]:
    return {"sslmode": "disable"}


@pytest.fixture(scope="session")
def cockroachdb_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.cockroachdb.yml")]


@pytest.fixture(scope="session")
def default_cockroachdb_service_name() -> str:
    return "cockroachdb"


@pytest.fixture(scope="session")
def cockroachdb_docker_ip(cockroachdb_docker_services: DockerServiceRegistry) -> str:
    return cockroachdb_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def cockroachdb_service(
    cockroachdb_docker_services: DockerServiceRegistry,
    default_cockroachdb_service_name: str,
    cockroachdb_docker_compose_files: list[Path],
    cockroachdb_port: int,
    cockroachdb_database: str,
    cockroachdb_driver_opts: dict[str, str],
) -> AsyncGenerator[None, None]:
    os.environ["COCKROACHDB_DATABASE"] = cockroachdb_database
    os.environ["COCKROACHDB_PORT"] = str(cockroachdb_port)
    await cockroachdb_docker_services.start(
        name=default_cockroachdb_service_name,
        docker_compose_files=cockroachdb_docker_compose_files,
        timeout=60,
        pause=1,
        check=cockroachdb_responsive,
        port=cockroachdb_port,
        database=cockroachdb_database,
        driver_opts=cockroachdb_driver_opts,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def cockroachdb_startup_connection(
    cockroachdb_service: DockerServiceRegistry,
    cockroachdb_docker_ip: str,
    cockroachdb_port: int,
    cockroachdb_database: str,
    cockroachdb_driver_opts: dict[str, str],
) -> AsyncGenerator[AsyncConnection[TupleRow], None]:
    opts = "&".join(f"{k}={v}" for k, v in cockroachdb_driver_opts.items()) if cockroachdb_driver_opts else ""
    async with await AsyncConnection.connect(
        f"cockroachdbql://root@{cockroachdb_docker_ip}:{cockroachdb_port}/{cockroachdb_database}?{opts}"
    ) as db_connection:
        yield db_connection
