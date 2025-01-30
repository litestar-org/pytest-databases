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
def xdist_cockroachdb_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclass
class CockroachDBService(ServiceContainer):
    database: str
    driver_opts: dict[str, str]


@pytest.fixture(scope="session")
def cockroachdb_driver_opts() -> dict[str, str]:
    return {"sslmode": "disable"}


@pytest.fixture(scope="session")
def cockroachdb_image() -> str:
    return "cockroachdb/cockroach:latest"


@pytest.fixture(scope="session")
def cockroachdb_service(
    docker_service: DockerService,
    xdist_cockroachdb_isolation_level: XdistIsolationLevel,
    cockroachdb_driver_opts: dict[str, str],
    cockroachdb_image: str,
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
    db_name = "pytest_databases"
    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_cockroachdb_isolation_level == "server":
            container_name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=cockroachdb_image,
        container_port=26257,
        check=cockroachdb_responsive,
        name=container_name,
        command="start-single-node --insecure",
        exec_after_start=f'cockroach sql --insecure -e "CREATE DATABASE {db_name}";',
        transient=xdist_cockroachdb_isolation_level == "server",
    ) as service:
        yield CockroachDBService(
            host=service.host,
            port=service.port,
            database=db_name,
            driver_opts=cockroachdb_driver_opts,
        )


@pytest.fixture(scope="session")
def cockroachdb_connection(
    cockroachdb_service: CockroachDBService,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[psycopg.Connection, None, None]:
    opts = "&".join(f"{k}={v}" for k, v in cockroachdb_driver_opts.items()) if cockroachdb_driver_opts else ""
    with psycopg.connect(
        f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
    ) as conn:
        yield conn
