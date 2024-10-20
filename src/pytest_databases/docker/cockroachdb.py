from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-cockroachdb-{simple_string_hash(__file__)}"


def cockroachdb_responsive(host: str, port: int, database: str, driver_opts: dict[str, str]) -> bool:
    opts = "&".join(f"{k}={v}" for k, v in driver_opts.items()) if driver_opts else ""
    try:
        conn = psycopg.connect(f"postgresql://root@{host}:{port}/{database}?{opts}")
    except Exception:  # noqa: BLE001
        return False

    try:
        db_open = conn.execute("SELECT 1").fetchone()
        return bool(db_open is not None and db_open[0] == 1)
    finally:
        conn.close()


@pytest.fixture(scope="session")
def cockroachdb_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def cockroachdb_docker_services(
    cockroachdb_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    with DockerServiceRegistry(worker_id, compose_project_name=cockroachdb_compose_project_name) as registry:
        yield registry


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
def cockroachdb_service(
    cockroachdb_docker_services: DockerServiceRegistry,
    default_cockroachdb_service_name: str,
    cockroachdb_docker_compose_files: list[Path],
    cockroachdb_port: int,
    cockroachdb_database: str,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[None, None, None]:
    os.environ["COCKROACHDB_DATABASE"] = cockroachdb_database
    os.environ["COCKROACHDB_PORT"] = str(cockroachdb_port)
    cockroachdb_docker_services.start(
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
def cockroachdb_startup_connection(
    cockroachdb_service: DockerServiceRegistry,
    cockroachdb_docker_ip: str,
    cockroachdb_port: int,
    cockroachdb_database: str,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[psycopg.Connection, None, None]:
    opts = "&".join(f"{k}={v}" for k, v in cockroachdb_driver_opts.items()) if cockroachdb_driver_opts else ""
    with psycopg.connect(
        f"postgresql://root@{cockroachdb_docker_ip}:{cockroachdb_port}/{cockroachdb_database}?{opts}"
    ) as conn:
        yield conn
