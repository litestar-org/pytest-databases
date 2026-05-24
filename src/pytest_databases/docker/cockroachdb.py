from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel


COCKROACHDB_USER = "root"
COCKROACHDB_DATABASE = "pytest_databases"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _exec_cockroach_sql(
    container: Container,
    sql: str,
    *,
    database: str = "defaultdb",
) -> tuple[int, bytes]:
    result = container.exec_run([
        "cockroach",
        "sql",
        "--insecure",
        "--host=localhost:26257",
        f"--database={database}",
        "--format=tsv",
        "-e",
        sql,
    ])
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _prepare_database(container: Container, database: str) -> None:
    quoted_database = _quote_identifier(database)
    last_output = b""
    for attempt in range(15):
        exit_code, output = _exec_cockroach_sql(
            container,
            f"CREATE DATABASE IF NOT EXISTS {quoted_database}",
        )
        if exit_code == 0:
            verify_code, verify_output = _exec_cockroach_sql(
                container,
                "SELECT 1",
                database=database,
            )
            if verify_code == 0:
                return
            last_output = verify_output
        else:
            last_output = output
        time.sleep(1 + attempt * 0.5)

    msg = f"CockroachDB database {database!r} could not be prepared. Last output: {last_output!r}"
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
def xdist_cockroachdb_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclasses.dataclass
class CockroachDBService(ServiceContainer):
    database: str


@pytest.fixture(scope="session")
def cockroachdb_image() -> str:
    return "cockroachdb/cockroach:latest"


@pytest.fixture(scope="session")
def cockroachdb_service(
    docker_service: DockerService,
    xdist_cockroachdb_isolation_level: XdistIsolationLevel,
    cockroachdb_image: str,
) -> Generator[CockroachDBService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        exit_code, _ = _exec_cockroach_sql(_service.container, "SELECT 1")
        return exit_code == 0

    container_name = "cockroachdb"
    db_name = COCKROACHDB_DATABASE
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
        check=check,
        name=container_name,
        command="start-single-node --insecure",
        transient=xdist_cockroachdb_isolation_level == "server",
    ) as service:
        _prepare_database(service.container, db_name)

        yield CockroachDBService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
        )
