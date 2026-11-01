"""IBM Db2 Community Edition container service fixtures and in-container CLI helpers."""

from __future__ import annotations

import os
import re
import shlex
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

__all__ = [
    "DB2_MAX_DB_NAME_LENGTH",
    "DB2_PORT",
    "DEFAULT_DB2_IMAGE",
    "Db2Service",
    "create_worker_database",
    "db2_dbname",
    "db2_host",
    "db2_image",
    "db2_password",
    "db2_port",
    "db2_service",
    "db2_startup_timeout",
    "db2_username",
    "exec_db2_sql",
    "provide_db2_service",
    "validate_db2_database_name",
    "xdist_db2_isolation_level",
]

DEFAULT_DB2_IMAGE = "icr.io/db2_community/db2:latest"
DB2_PORT = 50000
DB2_MAX_DB_NAME_LENGTH = 8
_DB2_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,7}$")


@dataclass
class Db2Service(ServiceContainer):
    """Connection metadata and CLI helpers for an IBM Db2 container service."""

    db_name: str
    username: str
    password: str

    @property
    def dsn(self) -> str:
        """The CLI/ODBC-style DSN string compatible with ``ibm_db.connect``."""
        return (
            f"DATABASE={self.db_name};"
            f"HOSTNAME={self.host};"
            f"PORT={self.port};"
            "PROTOCOL=TCPIP;"
            f"UID={self.username};"
            f"PWD={self.password};"
        )

    @property
    def connection_config(self) -> dict[str, str | int]:
        """Dictionary of connection parameters compatible with Db2 driver configurations."""
        return {
            "database": self.db_name,
            "hostname": self.host,
            "port": self.port,
            "protocol": "TCPIP",
            "user": self.username,
            "password": self.password,
        }

    def exec_sql(self, sql: str, *, db_name: str | None = None) -> str:
        """Execute a SQL statement inside the Db2 container without a host Python driver."""
        return exec_db2_sql(
            self.container,
            sql,
            db_name=db_name or self.db_name,
            instance_user=self.username,
        )

    def create_worker_database(self, db_name: str) -> None:
        """Create an isolated Db2 database inside the container."""
        create_worker_database(self.container, db_name, instance_user=self.username)


def validate_db2_database_name(db_name: str) -> str:
    """Validate that a Db2 database name conforms to the 8-character identifier rule.

    Args:
        db_name: Candidate Db2 database name.

    Returns:
        The validated database name.

    Raises:
        ValueError: If ``db_name`` exceeds 8 characters or contains invalid characters.
    """
    if len(db_name) > DB2_MAX_DB_NAME_LENGTH or not _DB2_NAME_PATTERN.match(db_name):
        msg = (
            f"Invalid Db2 database name {db_name!r}: must start with a letter, contain only "
            f"ASCII letters, digits, or underscores, and be at most {DB2_MAX_DB_NAME_LENGTH} characters."
        )
        raise ValueError(msg)
    return db_name


def exec_db2_sql(
    container: Container,
    sql: str,
    *,
    db_name: str,
    instance_user: str = "db2inst1",
) -> str:
    """Execute a SQL statement inside a running Db2 container via the ``db2`` CLI.

    Args:
        container: Running Db2 container.
        sql: SQL statement to execute.
        db_name: Target Db2 database name (at most 8 characters).
        instance_user: Db2 instance owner OS user inside the container.

    Returns:
        Decoded stdout/stderr from the ``db2`` command sequence.

    Raises:
        RuntimeError: If the ``db2`` CLI command returns a non-zero exit code.
    """
    validate_db2_database_name(db_name)
    inner_cmd = (
        f"db2 connect to {shlex.quote(db_name)} >/dev/null && db2 -x {shlex.quote(sql)} && db2 connect reset >/dev/null"
    )
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
    if result.exit_code != 0:
        msg = f"Db2 SQL command failed (exit {result.exit_code}): {output.strip()}"
        raise RuntimeError(msg)
    return output.strip()


def create_worker_database(
    container: Container,
    db_name: str,
    *,
    instance_user: str = "db2inst1",
) -> None:
    """Create a Db2 database inside the container if it does not already exist.

    Args:
        container: Running Db2 container.
        db_name: Target Db2 database name (at most 8 characters).
        instance_user: Db2 instance owner OS user inside the container.
    """
    validate_db2_database_name(db_name)
    inner_cmd = (
        f"db2 list db directory | grep -iq 'Database name.*= {db_name}' || db2 create database {shlex.quote(db_name)}"
    )
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    if result.exit_code != 0:
        output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
        msg = f"Failed to create Db2 database {db_name!r} (exit {result.exit_code}): {output.strip()}"
        raise RuntimeError(msg)


@contextmanager
def provide_db2_service(
    container_service: ContainerService,
    db2_image: str,
    db2_dbname: str,
    db2_username: str,
    db2_password: str,
    db2_startup_timeout: int,
    xdist_db2_isolation_level: XdistIsolationLevel,
) -> Generator[Db2Service, None, None]:
    """Start and yield a ready IBM Db2 Community Edition service container.

    Yields:
        A configured Db2Service instance.
    """
    worker_num = get_xdist_worker_num()
    name = "db2"
    initial_db = (
        validate_db2_database_name(os.getenv("DB2_DBNAME", "pytestdb"))
        if worker_num is not None and xdist_db2_isolation_level == "database"
        else db2_dbname
    )
    if worker_num is not None and xdist_db2_isolation_level == "server":
        name = f"db2_{worker_num + 1}"

    def check(service: ServiceContainer) -> bool:
        try:
            output = exec_db2_sql(
                service.container,
                "SELECT 1 FROM SYSIBM.SYSDUMMY1",
                db_name=initial_db,
                instance_user=db2_username,
            )
        except RuntimeError:
            return False
        return "1" in output

    with container_service.run(
        image=db2_image,
        container_port=DB2_PORT,
        name=name,
        env={
            "LICENSE": "accept",
            "DB2INST1_PASSWORD": db2_password,
            "DBNAME": initial_db,
            "SAMPLEDB": "false",
            "AUTOCONFIG": "false",
            "ARCHIVE_LOGS": "false",
            "TO_CREATE_SAMPLEDB": "false",
            "REPODB": "false",
        },
        wait_for_log="Setup has completed",
        check=check,
        timeout=db2_startup_timeout,
        pause=2.0,
        transient=xdist_db2_isolation_level == "server",
        privileged=True,
        ipc_mode="host",
    ) as service:
        if db2_dbname != initial_db:
            create_worker_database(service.container, db2_dbname, instance_user=db2_username)
        yield Db2Service(
            container=service.container,
            host=service.host,
            port=service.port,
            db_name=db2_dbname,
            username=db2_username,
            password=db2_password,
        )


@pytest.fixture(scope="session")
def xdist_db2_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for Db2."""
    return "database"


@pytest.fixture(scope="session")
def db2_image() -> str:
    """Provide the IBM Db2 Community Edition container image."""
    return os.getenv("DB2_IMAGE", DEFAULT_DB2_IMAGE)


@pytest.fixture(scope="session")
def db2_username() -> str:
    """Provide the Db2 instance owner username."""
    return os.getenv("DB2_USER", "db2inst1")


@pytest.fixture(scope="session")
def db2_password() -> str:
    """Provide the Db2 instance owner password."""
    return os.getenv("DB2_PASSWORD", "pytest_db2_pwd")


@pytest.fixture(scope="session")
def db2_dbname(xdist_db2_isolation_level: XdistIsolationLevel) -> str:
    """Provide an 8-character-compliant Db2 database name."""
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_db2_isolation_level == "database":
        return validate_db2_database_name(f"ptdb_{worker_num}")
    return validate_db2_database_name(os.getenv("DB2_DBNAME", "pytestdb"))


@pytest.fixture(scope="session")
def db2_startup_timeout() -> int:
    """Provide the startup timeout in seconds for Db2 container initialization."""
    return int(os.getenv("DB2_STARTUP_TIMEOUT", "600"))


@pytest.fixture(scope="session")
def db2_host(db2_service: Db2Service) -> str:
    """Provide the mapped host address for the Db2 service."""
    return db2_service.host


@pytest.fixture(scope="session")
def db2_port(db2_service: Db2Service) -> int:
    """Provide the mapped host port for the Db2 service."""
    return db2_service.port


@pytest.fixture(scope="session")
def db2_service(
    container_service: ContainerService,
    db2_image: str,
    db2_dbname: str,
    db2_username: str,
    db2_password: str,
    db2_startup_timeout: int,
    xdist_db2_isolation_level: XdistIsolationLevel,
) -> Generator[Db2Service, None, None]:
    """Start and yield a ready IBM Db2 Community Edition service container.

    Yields:
        A configured Db2Service instance.
    """
    with provide_db2_service(
        container_service=container_service,
        db2_image=db2_image,
        db2_dbname=db2_dbname,
        db2_username=db2_username,
        db2_password=db2_password,
        db2_startup_timeout=db2_startup_timeout,
        xdist_db2_isolation_level=xdist_db2_isolation_level,
    ) as service:
        yield service
