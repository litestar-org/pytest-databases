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
    "db2_4k_device_support",
    "db2_dbname",
    "db2_image",
    "db2_password",
    "db2_service",
    "db2_startup_timeout",
    "db2_username",
    "exec_db2_sql",
    "provide_db2_service",
    "validate_db2_database_name",
    "xdist_db2_isolation_level",
]

DEFAULT_DB2_IMAGE = "icr.io/db2_community/db2:12.1.5.0"
DB2_PORT = 50000
DB2_MAX_DB_NAME_LENGTH = 8
_DB2_4K_REGISTRY_SETTINGS: tuple[tuple[str, str], ...] = (("DB2_4K_DEVICE_SUPPORT", "ON"), ("DB2_DIRECT_IO", "NO"))
_CLP_MAX_SUCCESS_EXIT_CODE = 3
_DB2_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,7}$")
_DB2_SETUP_SCRIPT = "/var/db2_setup/lib/setup_db2_instance.sh"
_DB2_SETUP_FUNCTIONS = "/var/db2_setup/include/db2_common_functions"
_DB2_4K_MISSING_DATABASE_MARKERS = ("SQL1013N", "SQL0293N")


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

    The command line processor exits with 1 when a statement finds no rows (``SQL0100W``) and with 2 for other
    warnings. Both count as success, and the CLP message text is part of the returned output so callers can inspect
    it. Exit codes of 4 and above (errors) raise. All ``db2`` calls run in one shell process because the CLP back end,
    and therefore the connection, is tied to the calling shell; the connect output goes to a file instead of a command
    substitution for that reason.

    Args:
        container: Running Db2 container.
        sql: SQL statement to execute.
        db_name: Target Db2 database name (at most 8 characters).
        instance_user: Db2 instance owner OS user inside the container.

    Returns:
        Decoded stdout/stderr from the ``db2`` command sequence, including any warning text.

    Raises:
        RuntimeError: If connecting or executing the statement fails with a CLP exit code of 4 or higher.
    """
    validate_db2_database_name(db_name)
    inner_cmd = (
        'log="$HOME/.pytest-databases-connect.$$"; '
        f'db2 connect to {shlex.quote(db_name)} > "$log" 2>&1; rc=$?; '
        f'if [ "$rc" -gt {_CLP_MAX_SUCCESS_EXIT_CODE} ]; then cat "$log"; rm -f "$log"; exit "$rc"; fi; '
        'rm -f "$log"; '
        f"db2 -x {shlex.quote(sql)}; rc=$?; "
        'db2 connect reset >/dev/null; exit "$rc"'
    )
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
    if result.exit_code is None or result.exit_code > _CLP_MAX_SUCCESS_EXIT_CODE:
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
        f"db2 list db directory | grep -Eiq '^[[:space:]]*Database name[[:space:]]*= {db_name}[[:space:]]*$' "
        f"|| db2 create database {shlex.quote(db_name)}"
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
    *,
    enable_4k_device_support: bool = True,
) -> Generator[Db2Service, None, None]:
    """Start and yield a ready IBM Db2 Community Edition service container.

    With ``enable_4k_device_support`` (the default) the instance runs with ``DB2_4K_DEVICE_SUPPORT=ON`` and
    ``DB2_DIRECT_IO=NO`` so database creation works when the container storage has 4096-byte logical sectors.
    The image setup script is patched to set both registry variables before its first ``db2start``; if the initial
    database is still missing after setup (``SQL1013N``), the variables are set, the instance is restarted, and the
    database is created once.

    Args:
        container_service: The container service manager.
        db2_image: IBM Db2 Community Edition container image.
        db2_dbname: Database name for the active worker.
        db2_username: Db2 instance owner username.
        db2_password: Db2 instance owner password.
        db2_startup_timeout: Startup timeout in seconds.
        xdist_db2_isolation_level: xdist isolation strategy (database or server).
        enable_4k_device_support: Whether to apply the 4096-byte sector registry settings.

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
    transient = False
    if worker_num is not None and xdist_db2_isolation_level == "server":
        name = f"db2_{worker_num}"
        transient = True

    recreate_attempted = False

    def check(service: ServiceContainer) -> bool:
        nonlocal recreate_attempted
        try:
            output = exec_db2_sql(
                service.container,
                "SELECT 1 FROM SYSIBM.SYSDUMMY1",
                db_name=initial_db,
                instance_user=db2_username,
            )
        except RuntimeError as exc:
            missing = any(marker in str(exc) for marker in _DB2_4K_MISSING_DATABASE_MARKERS)
            if enable_4k_device_support and missing and not recreate_attempted:
                recreate_attempted = True
                _create_database_with_4k_device_support(service.container, initial_db, instance_user=db2_username)
            return False
        return output == "1"

    entrypoint: list[str] | None = None
    command: list[str] | None = None
    if enable_4k_device_support:
        entrypoint = ["/bin/bash", "-c"]
        command = [_db2_4k_setup_command()]

    with container_service.run(
        image=db2_image,
        container_port=DB2_PORT,
        name=name,
        command=command,
        entrypoint=entrypoint,
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
        transient=transient,
        privileged=True,
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


def _db2_4k_setup_command() -> str:
    """Build the container command that applies the 4096-byte sector registry settings before Db2 setup runs.

    The image setup runs ``db2set DB2COMM=TCPIP`` in ``set_dbm_cfg`` before its first ``db2start`` and before the
    initial database is created, so the extra ``db2set`` calls are chained onto that line.

    Returns:
        A ``bash -c`` script that patches the setup functions and then execs the image setup script.
    """
    extra = "".join(f" \\&\\& db2set {key}={value}" for key, value in _DB2_4K_REGISTRY_SETTINGS)
    expression = f"s/db2set DB2COMM=TCPIP/db2set DB2COMM=TCPIP{extra}/"
    return f"sed -i {shlex.quote(expression)} {_DB2_SETUP_FUNCTIONS} && exec {_DB2_SETUP_SCRIPT}"


def _create_database_with_4k_device_support(container: Container, db_name: str, *, instance_user: str) -> None:
    """Apply the 4096-byte sector registry settings, restart the instance, and create ``db_name`` if missing.

    Args:
        container: Running Db2 container.
        db_name: Database name to create.
        instance_user: Db2 instance owner OS user inside the container.

    Raises:
        RuntimeError: If any step exits non-zero.
    """
    validate_db2_database_name(db_name)
    registry = " && ".join(f"db2set {key}={value}" for key, value in _DB2_4K_REGISTRY_SETTINGS)
    inner_cmd = (
        f"db2 list db directory | grep -Eiq '^[[:space:]]*Database name[[:space:]]*= {db_name}[[:space:]]*$' "
        f"|| ({registry} && db2stop force && db2start && db2 create database {shlex.quote(db_name)})"
    )
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    if result.exit_code != 0:
        output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
        msg = f"Failed to create Db2 database {db_name!r} (exit {result.exit_code}): {output.strip()}"
        raise RuntimeError(msg)


@pytest.fixture(scope="session")
def xdist_db2_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for Db2."""
    return "database"


@pytest.fixture(scope="session")
def db2_4k_device_support() -> bool:
    """Whether Db2 runs with ``DB2_4K_DEVICE_SUPPORT=ON`` and ``DB2_DIRECT_IO=NO``.

    Enabled by default so database creation works on storage with 4096-byte logical sectors. Set the
    ``DB2_4K_DEVICE_SUPPORT`` environment variable to ``0``/``false``/``no``/``off`` or override this fixture to
    return ``False`` to keep the image defaults.
    """
    return os.getenv("DB2_4K_DEVICE_SUPPORT", "on").strip().lower() not in {"0", "false", "no", "off"}


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
def db2_service(
    container_service: ContainerService,
    db2_image: str,
    db2_dbname: str,
    db2_username: str,
    db2_password: str,
    db2_startup_timeout: int,
    xdist_db2_isolation_level: XdistIsolationLevel,
    db2_4k_device_support: bool,
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
        enable_4k_device_support=db2_4k_device_support,
    ) as service:
        yield service
