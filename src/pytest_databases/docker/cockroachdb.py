from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import asyncpg
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-cockroachdb-{simple_string_hash(__file__)}"


async def cockroachdb_responsive(host: str, port: int, database: str, driver_opts: dict[str, str]) -> bool:
    opts = "&".join(f"{k}={v}" for k, v in driver_opts.items()) if driver_opts else ""
    try:
        conn = await asyncpg.connect(f"postgresql://root@{host}:{port}/{database}?{opts}")
    except Exception:  # noqa: BLE001
        return False

    try:
        db_open = await conn.fetchrow("SELECT 1")
        return bool(db_open is not None and db_open[0] == 1)
    finally:
        await conn.close()


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
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    opts = "&".join(f"{k}={v}" for k, v in cockroachdb_driver_opts.items()) if cockroachdb_driver_opts else ""
    conn = await asyncpg.connect(
        f"postgresql://root@{cockroachdb_docker_ip}:{cockroachdb_port}/{cockroachdb_database}?{opts}"
    )
    try:
        yield conn
    finally:
        await conn.close()
