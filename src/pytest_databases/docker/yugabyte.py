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
def xdist_yugabyte_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclass
class YugabyteService(ServiceContainer):
    database: str
    driver_opts: dict[str, str]


@pytest.fixture(scope="session")
def yugabyte_driver_opts() -> dict[str, str]:
    return {"sslmode": "disable"}


@pytest.fixture(scope="session")
def yugabyte_image() -> str:
    return "software.yugabyte.com/yugabytedb/yugabyte:latest"


@pytest.fixture(scope="session")
def yugabyte_service(
    docker_service: DockerService,
    xdist_yugabyte_isolation_level: XdistIsolationLevel,
    yugabyte_driver_opts: dict[str, str],
    yugabyte_image: str,
) -> Generator[YugabyteService, None, None]:
    def yugabyte_responsive(_service: ServiceContainer) -> bool:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_driver_opts.items()) if yugabyte_driver_opts else ""
        try:
            conn = psycopg.connect(f"postgresql://yugabyte:yugabyte@{_service.host}:{_service.port}/yugabyte?{opts}")
        except Exception:  # noqa: BLE001
            return False

        try:
            db_open = conn.execute("SELECT 1").fetchone()
            return bool(db_open is not None and db_open[0] == 1)
        finally:
            conn.close()

    container_name = "yugabyte"
    db_name = "pytest_databases"
    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_yugabyte_isolation_level == "server":
            container_name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=yugabyte_image,
        container_port=5433,  # YugabyteDB YSQL port (not CockroachDB's 26257)
        check=yugabyte_responsive,
        name=container_name,
        command="bin/yugabyted start --background=false",
        exec_after_start=f"sh -c 'bin/ysqlsh -h $(hostname) -U yugabyte -d yugabyte -c \"CREATE DATABASE {db_name};\"'",
        transient=xdist_yugabyte_isolation_level == "server",
        timeout=60,  # YugabyteDB needs longer startup time
    ) as service:
        yield YugabyteService(
            host=service.host,
            port=service.port,
            database=db_name,
            driver_opts=yugabyte_driver_opts,
        )


@pytest.fixture(scope="session")
def yugabyte_connection(
    yugabyte_service: YugabyteService,
    yugabyte_driver_opts: dict[str, str],
) -> Generator[psycopg.Connection, None, None]:
    opts = "&".join(f"{k}={v}" for k, v in yugabyte_driver_opts.items()) if yugabyte_driver_opts else ""
    with psycopg.connect(
        f"postgresql://yugabyte:yugabyte@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"
    ) as conn:
        yield conn
