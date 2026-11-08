"""Doltgres (PostgreSQL-compatible version-controlled database) container service fixtures."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num, tcp_port_open
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

__all__ = (
    "DOLTGRES_DATABASE",
    "DOLTGRES_IMAGE",
    "DOLTGRES_PASSWORD",
    "DOLTGRES_ROOT_USER",
    "DOLTGRES_USER",
    "DoltgresService",
    "doltgres_database",
    "doltgres_image",
    "doltgres_password",
    "doltgres_port",
    "doltgres_root_password",
    "doltgres_service",
    "doltgres_user",
    "exec_doltgres_psql",
    "provide_doltgres_service",
    "xdist_doltgres_isolation_level",
)

DOLTGRES_IMAGE = "dolthub/doltgresql:latest"
DOLTGRES_ROOT_USER = "postgres"
DOLTGRES_USER = "doltgres"
DOLTGRES_PASSWORD = "super-secret"
DOLTGRES_DATABASE = "pytest_databases"


@dataclass
class DoltgresService(ServiceContainer):
    """Service handle for a running Doltgres container."""

    database: str
    user: str
    password: str

    @property
    def db(self) -> str:
        """Alias for ``database`` matching ``DoltService.db``."""
        return self.database


def exec_doltgres_psql(
    container: Container,
    sql: str,
    *,
    user: str = DOLTGRES_ROOT_USER,
    password: str,
    database: str = "postgres",
) -> tuple[int, bytes]:
    """Execute a SQL statement inside a Doltgres container via bundled ``psql``.

    Args:
        container: Running Doltgres container.
        sql: SQL statement to execute.
        user: Database user name.
        password: Password for ``user``.
        database: Target database name.

    Returns:
        Tuple of ``(exit_code, raw_output_bytes)``.
    """
    try:
        result = container.exec_run(
            [
                "psql",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                user,
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-tAc",
                sql,
            ],
            environment={"PGPASSWORD": password},
        )
    except (APIError, NotFound) as exc:
        return -1, str(exc).encode()
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


@contextlib.contextmanager
def provide_doltgres_service(
    docker_service: DockerService,
    *,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    user: str,
    password: str,
    root_password: str,
    database: str,
    port: int | None = None,
) -> Generator[DoltgresService, None, None]:
    """Start and manage a Doltgres container service.

    Yields:
        Active ``DoltgresService`` instance.

    Raises:
        RuntimeError: If database or role initialization fails across retries.
    """

    def check(_service: ServiceContainer) -> bool:
        try:
            init_res = _service.container.exec_run(["test", "-f", "/var/lib/doltgres/.init_completed"])
        except (APIError, NotFound):
            return False
        if init_res.exit_code != 0:
            return False
        exit_code, output = exec_doltgres_psql(
            _service.container,
            "SELECT 1",
            user=DOLTGRES_ROOT_USER,
            password=root_password,
            database="postgres",
        )
        return exit_code == 0 and output.strip() == b"1" and tcp_port_open(_service.host, _service.port)

    container_name = name
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
        check=check,
        container_port=5432,
        host_port=port,
        name=container_name,
        env={
            "DOLTGRES_USER": DOLTGRES_ROOT_USER,
            "DOLTGRES_PASSWORD": root_password,
            "DOLTGRES_DB": "postgres",
        },
        timeout=120,
        pause=1.0,
        transient=isolation_level == "server",
    ) as service:
        _prepare_doltgres_database(
            service.container,
            container_name=container_name,
            database=db_name,
            user=user,
            password=password,
            root_password=root_password,
        )

        yield DoltgresService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def xdist_doltgres_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for Doltgres."""
    return "database"


@pytest.fixture(scope="session")
def doltgres_image() -> str:
    """Return the Doltgres container image."""
    return os.getenv("DOLTGRES_IMAGE", DOLTGRES_IMAGE)


@pytest.fixture(scope="session")
def doltgres_user() -> str:
    """Return the Doltgres application user."""
    return os.getenv("DOLTGRES_USER", DOLTGRES_USER)


@pytest.fixture(scope="session")
def doltgres_password() -> str:
    """Return the Doltgres application password."""
    return os.getenv("DOLTGRES_PASSWORD", DOLTGRES_PASSWORD)


@pytest.fixture(scope="session")
def doltgres_root_password() -> str:
    """Return the Doltgres superuser password."""
    return os.getenv("DOLTGRES_ROOT_PASSWORD", DOLTGRES_PASSWORD)


@pytest.fixture(scope="session")
def doltgres_database() -> str:
    """Return the Doltgres database name."""
    return os.getenv("DOLTGRES_DATABASE", DOLTGRES_DATABASE)


@pytest.fixture(scope="session")
def doltgres_port() -> int | None:
    """Return an optional pinned host port for Doltgres from ``DOLTGRES_PORT``."""
    raw = os.getenv("DOLTGRES_PORT")
    return int(raw) if raw else None


@pytest.fixture(autouse=False, scope="session")
def doltgres_service(
    docker_service: DockerService,
    xdist_doltgres_isolation_level: XdistIsolationLevel,
    doltgres_image: str,
    doltgres_user: str,
    doltgres_password: str,
    doltgres_root_password: str,
    doltgres_database: str,
    doltgres_port: int | None,
) -> Generator[DoltgresService, None, None]:
    """Provide a running Doltgres container service.

    Yields:
        Active ``DoltgresService`` instance.
    """
    with provide_doltgres_service(
        docker_service=docker_service,
        image=doltgres_image,
        name="doltgres",
        isolation_level=xdist_doltgres_isolation_level,
        user=doltgres_user,
        password=doltgres_password,
        root_password=doltgres_root_password,
        database=doltgres_database,
        port=doltgres_port,
    ) as service:
        yield service


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _quote_literal(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


def _ensure_doltgres_user(
    container: Container,
    *,
    user: str,
    password: str,
    root_password: str,
) -> tuple[bool, bytes]:
    if user == DOLTGRES_ROOT_USER:
        return True, b""
    quoted_user = _quote_identifier(user)
    quoted_password = _quote_literal(password)
    create_code, create_out = exec_doltgres_psql(
        container,
        f"CREATE USER {quoted_user} WITH SUPERUSER PASSWORD {quoted_password}",
        user=DOLTGRES_ROOT_USER,
        password=root_password,
        database="postgres",
    )
    if create_code == 0 or b"already exists" in create_out.lower():
        alter_code, alter_out = exec_doltgres_psql(
            container,
            f"ALTER USER {quoted_user} WITH SUPERUSER PASSWORD {quoted_password}",
            user=DOLTGRES_ROOT_USER,
            password=root_password,
            database="postgres",
        )
        if alter_code == 0 or create_code == 0:
            return True, b""
        return False, alter_out
    return False, create_out


def _ensure_doltgres_database(
    container: Container,
    *,
    database: str,
    user: str,
    root_password: str,
) -> tuple[bool, bytes]:
    quoted_db = _quote_identifier(database)
    quoted_user = _quote_identifier(user)
    create_code, create_out = exec_doltgres_psql(
        container,
        f"CREATE DATABASE {quoted_db}",
        user=DOLTGRES_ROOT_USER,
        password=root_password,
        database="postgres",
    )
    if create_code != 0 and b"already exists" not in create_out.lower():
        return False, create_out
    if user != DOLTGRES_ROOT_USER:
        grant_code, grant_out = exec_doltgres_psql(
            container,
            f"GRANT ALL PRIVILEGES ON DATABASE {quoted_db} TO {quoted_user}",
            user=DOLTGRES_ROOT_USER,
            password=root_password,
            database="postgres",
        )
        if grant_code != 0:
            return False, grant_out
    return True, b""


def _prepare_doltgres_database(
    container: Container,
    *,
    container_name: str,
    database: str,
    user: str,
    password: str,
    root_password: str,
) -> None:
    last_err = b""
    for attempt in range(10):
        user_ok, user_err = _ensure_doltgres_user(
            container,
            user=user,
            password=password,
            root_password=root_password,
        )
        if not user_ok:
            last_err = user_err
        else:
            db_ok, db_err = _ensure_doltgres_database(
                container,
                database=database,
                user=user,
                root_password=root_password,
            )
            if not db_ok:
                last_err = db_err
            else:
                verify_code, verify_out = exec_doltgres_psql(
                    container,
                    "SELECT 1",
                    user=user,
                    password=password,
                    database=database,
                )
                if verify_code == 0 and verify_out.strip() == b"1":
                    return
                last_err = verify_out
        time.sleep(0.5 * (attempt + 1))

    msg = (
        f"Doltgres fixture {container_name!r}: user {user!r} could not reach database "
        f"{database!r} after 10 attempts. Last output: {last_err!r}"
    )
    raise RuntimeError(msg)
