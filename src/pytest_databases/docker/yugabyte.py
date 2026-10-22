"""YugabyteDB distributed SQL service fixtures."""

from __future__ import annotations

import contextlib
import shlex
import socket
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = (
    "YUGABYTE_DATABASE",
    "YUGABYTE_DB",
    "YUGABYTE_PASSWORD",
    "YUGABYTE_TSERVER_FLAGS",
    "YUGABYTE_USER",
    "YugabyteService",
    "provide_yugabyte_service",
    "xdist_yugabyte_isolation_level",
    "yugabyte_database",
    "yugabyte_image",
    "yugabyte_password",
    "yugabyte_service",
    "yugabyte_user",
)

YUGABYTE_USER = "yugabyte"
YUGABYTE_PASSWORD = "yugabyte"
YUGABYTE_DB = "yugabyte"
YUGABYTE_DATABASE = "pytest_databases"
YUGABYTE_TSERVER_FLAGS = "reject_writes_min_disk_space_mb=128"


@dataclass
class YugabyteService(ServiceContainer):
    """Service container metadata for YugabyteDB."""

    database: str
    user: str
    password: str


@contextlib.contextmanager
def provide_yugabyte_service(
    docker_service: DockerService,
    *,
    isolation_level: XdistIsolationLevel,
    image: str,
    user: str,
    password: str,
    database: str,
) -> Generator[YugabyteService, None, None]:
    """Start a YugabyteDB container, provision the test role and database, and verify readiness.

    Yields:
        YugabyteService: Started YugabyteDB container service metadata.
    """

    def yugabyte_responsive(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_ysqlsh(_service.container, "SELECT 1")
        return exit_code == 0 and output.strip() == b"1"

    container_name = "yugabyte"
    db_name = database
    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if isolation_level == "server":
            container_name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=image,
        container_port=5433,
        check=yugabyte_responsive,
        name=container_name,
        command=f"bin/yugabyted start --background=false --tserver_flags={YUGABYTE_TSERVER_FLAGS}",
        transient=isolation_level == "server",
        timeout=120,
        pause=1.0,
    ) as service:
        _prepare_yugabyte_database(
            service.container,
            container_name,
            db_name,
            user,
            password,
        )

        last_output = b""
        for attempt in range(5):
            endpoint_code, endpoint_output = _validate_mapped_endpoint(
                service,
                db_name,
                user,
                password,
            )
            if endpoint_code == 0 and endpoint_output.strip() == b"1":
                break
            last_output = endpoint_output
            time.sleep(1 + attempt * 0.5)
        else:
            msg = (
                f"Yugabyte fixture {container_name!r}: mapped endpoint {service.host}:{service.port} "
                f"was not ready after 5 attempts. Last output: {last_output!r}"
            )
            raise RuntimeError(msg)

        yield YugabyteService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def xdist_yugabyte_isolation_level() -> XdistIsolationLevel:
    """Default ``pytest-xdist`` isolation level for YugabyteDB."""
    return "database"


@pytest.fixture(scope="session")
def yugabyte_image() -> str:
    """Default YugabyteDB container image."""
    return "software.yugabyte.com/yugabytedb/yugabyte:latest"


@pytest.fixture(scope="session")
def yugabyte_user() -> str:
    """Default YugabyteDB user."""
    return YUGABYTE_USER


@pytest.fixture(scope="session")
def yugabyte_password() -> str:
    """Default YugabyteDB password."""
    return YUGABYTE_PASSWORD


@pytest.fixture(scope="session")
def yugabyte_database() -> str:
    """Default YugabyteDB database name."""
    return YUGABYTE_DATABASE


@pytest.fixture(scope="session")
def yugabyte_service(
    docker_service: DockerService,
    xdist_yugabyte_isolation_level: XdistIsolationLevel,
    yugabyte_image: str,
    yugabyte_user: str,
    yugabyte_password: str,
    yugabyte_database: str,
) -> Generator[YugabyteService, None, None]:
    """Provide a session-scoped YugabyteDB service container.

    Yields:
        YugabyteService: Started YugabyteDB container service metadata.
    """
    with provide_yugabyte_service(
        docker_service,
        isolation_level=xdist_yugabyte_isolation_level,
        image=yugabyte_image,
        user=yugabyte_user,
        password=yugabyte_password,
        database=yugabyte_database,
    ) as service:
        yield service


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _quote_literal(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


def _make_ysqlsh_command(
    sql: str,
    *,
    database: str = YUGABYTE_DB,
    user: str = YUGABYTE_USER,
    host: str = "$(hostname)",
    port: int | None = None,
) -> str:
    command_parts = [
        "bin/ysqlsh",
        f"-h {host}",
    ]
    if port is not None:
        command_parts.append(f"-p {port}")
    command_parts.extend([
        f"-U {shlex.quote(user)}",
        f"-d {shlex.quote(database)}",
        "-tAc",
        shlex.quote(sql),
    ])
    return " ".join(command_parts)


def _exec_ysqlsh(
    container: Container,
    sql: str,
    *,
    database: str = YUGABYTE_DB,
    user: str = YUGABYTE_USER,
    password: str | None = None,
) -> tuple[int, bytes]:
    environment = {"PGPASSWORD": password} if password is not None else None
    result = container.exec_run(
        [
            "sh",
            "-c",
            _make_ysqlsh_command(sql, database=database, user=user),
        ],
        environment=environment,
    )
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


def _make_role_sql(user: str, password: str) -> str:
    quoted_user = _quote_identifier(user)
    quoted_password = _quote_literal(password)
    quoted_user_literal = _quote_literal(user)
    return (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = {quoted_user_literal}) THEN "
        f"CREATE ROLE {quoted_user} LOGIN PASSWORD {quoted_password}; "
        "ELSE "
        f"ALTER ROLE {quoted_user} WITH LOGIN PASSWORD {quoted_password}; "
        "END IF; "
        "END $$;"
    )


def _ensure_yugabyte_role(container: Container, user: str, password: str) -> tuple[bool, bytes]:
    exit_code, output = _exec_ysqlsh(container, _make_role_sql(user, password))
    return exit_code == 0, output


def _ensure_yugabyte_database(container: Container, database: str, user: str) -> tuple[bool, bytes]:
    quoted_database = _quote_identifier(database)
    quoted_database_literal = _quote_literal(database)
    quoted_user = _quote_identifier(user)
    exists_code, exists_output = _exec_ysqlsh(
        container,
        f"SELECT 1 FROM pg_database WHERE datname = {quoted_database_literal}",
    )
    if exists_code != 0:
        return False, exists_output

    if exists_output.strip() != b"1":
        create_code, create_output = _exec_ysqlsh(container, f"CREATE DATABASE {quoted_database} OWNER {quoted_user}")
        if create_code != 0:
            return False, create_output

    grant_code, grant_output = _exec_ysqlsh(
        container,
        f"GRANT ALL PRIVILEGES ON DATABASE {quoted_database} TO {quoted_user}",
    )
    if grant_code != 0:
        return False, grant_output

    schema_code, schema_output = _exec_ysqlsh(
        container,
        f"GRANT ALL PRIVILEGES ON SCHEMA public TO {quoted_user}",
        database=database,
    )
    return schema_code == 0, schema_output


def _verify_yugabyte_database_access(
    container: Container,
    database: str,
    user: str,
    password: str,
) -> tuple[bool, bytes]:
    exit_code, output = _exec_ysqlsh(
        container,
        "SELECT 1",
        database=database,
        user=user,
        password=password,
    )
    return exit_code == 0 and output.strip() == b"1", output


def _prepare_yugabyte_database(
    container: Container,
    container_name: str,
    database: str,
    user: str,
    password: str,
) -> None:
    last_output = b""
    for attempt in range(15):
        role_ready, role_output = _ensure_yugabyte_role(container, user, password)
        database_ready, database_output = (
            _ensure_yugabyte_database(container, database, user) if role_ready else (False, role_output)
        )
        access_ready, access_output = (
            _verify_yugabyte_database_access(container, database, user, password)
            if database_ready
            else (False, database_output)
        )
        if access_ready:
            return

        last_output = access_output
        time.sleep(1 + attempt * 0.5)

    msg = (
        f"Yugabyte fixture {container_name!r}: user {user!r} could not reach database "
        f"{database!r} after 15 attempts. Last output: {last_output!r}"
    )
    raise RuntimeError(msg)


def _validate_mapped_endpoint(
    service: ServiceContainer,
    database: str,
    user: str,
    password: str,
) -> tuple[int, bytes]:
    try:
        with socket.create_connection((service.host, service.port), timeout=2.0):
            pass
    except OSError as exc:
        return 1, str(exc).encode()
    ready, output = _verify_yugabyte_database_access(service.container, database, user, password)
    return (0 if ready else 1), output
