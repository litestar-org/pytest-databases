from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import psycopg
import pytest

from pytest_databases._service import DockerService, ServiceContainer
from pytest_databases.helpers import get_xdist_worker_num

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases.types import XdistIsolationLevel


@pytest.fixture(scope="session")
def cockroachdb_xdist_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclass
class CockroachDBService(ServiceContainer):
    database: str
    driver_opts: dict[str, str]


@pytest.fixture(scope="session")
def cockroachdb_driver_opts() -> dict[str, str]:
    return {"sslmode": "disable"}


@pytest.fixture(scope="session")
def cockroachdb_service(
    docker_service: DockerService,
    cockroachdb_xdist_isolation_level: XdistIsolationLevel,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[CockroachDBService, None, None]:
    def cockroachdb_responsive(_service: ServiceContainer) -> bool:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_driver_opts.items()) if cockroachdb_driver_opts else ""
        try:
            conn = psycopg.connect(f"postgresql://root@{_service.host}:{_service.port}/defaultdb?{opts}")
        except Exception:  # noqa: BLE001
            return False

        try:
            db_open = conn.execute("SELECT 1").fetchone()
            return bool(db_open is not None and db_open[0] == 1)
        finally:
            conn.close()

    container_name = "cockroachdb"

    worker_num = get_xdist_worker_num()
    if cockroachdb_xdist_isolation_level == "server":
        container_name = f"container_name_{worker_num}"

    db_name = f"pytest_{worker_num + 1}"

    with docker_service.run(
        image="cockroachdb/cockroach:latest",
        container_port=26257,
        check=cockroachdb_responsive,
        name=container_name,
        command="start-single-node --insecure",
        exec_after_start=f'cockroach sql --insecure -e "CREATE DATABASE {db_name}";',
        transient=cockroachdb_xdist_isolation_level == "server",
    ) as service:
        yield CockroachDBService(
            host=service.host,
            port=service.port,
            database=db_name,
            driver_opts=cockroachdb_driver_opts,
        )


@pytest.fixture(scope="session")
def cockroachdb_startup_connection(
    cockroachdb_service: CockroachDBService,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[psycopg.Connection, None, None]:
    opts = "&".join(f"{k}={v}" for k, v in cockroachdb_driver_opts.items()) if cockroachdb_driver_opts else ""
    with psycopg.connect(
        f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
    ) as conn:
        yield conn
