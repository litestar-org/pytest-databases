"""SAP Sybase ASE (Adaptive Server Enterprise) container service fixtures."""

from __future__ import annotations

import dataclasses
import os
import re
import shlex
import socket
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

__all__ = (
    "DEFAULT_SYBASE_IMAGE",
    "SYBASE_DATABASE",
    "SYBASE_MAX_DB_NAME_LENGTH",
    "SYBASE_PASSWORD",
    "SYBASE_PORT",
    "SYBASE_USER",
    "SybaseService",
    "create_worker_database",
    "exec_isql",
    "provide_sybase_service",
    "sybase_database",
    "sybase_image",
    "sybase_password",
    "sybase_service",
    "sybase_startup_timeout",
    "sybase_user",
    "validate_sybase_database_name",
    "xdist_sybase_isolation_level",
)

DEFAULT_SYBASE_IMAGE = "datagrip/sybase:16.0"
SYBASE_PORT = 5000
SYBASE_USER = "sa"
SYBASE_PASSWORD = "myPassword"
SYBASE_DATABASE = "master"
SYBASE_MAX_DB_NAME_LENGTH = 30
_SYBASE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,29}$")

ISQL_CANDIDATES: tuple[str, ...] = (
    "/opt/sybase/OCS-16_0/bin/isql",
    "/opt/sybase/OCS-15_0/bin/isql",
    "isql",
    "sqsh",
)


@dataclasses.dataclass
class SybaseService(ServiceContainer):
    """Service handle for a running SAP Sybase ASE container."""

    user: str
    password: str
    database: str

    @property
    def connection_config(self) -> dict[str, str | int | bool]:
        """Connection configuration parameters compatible with Sybase drivers."""
        return {
            "server": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "autocommit": True,
        }

    @property
    def dsn(self) -> str:
        """TDS connection string representation."""
        return (
            f"DRIVER={{FreeTDS}};SERVER={self.host};PORT={self.port};"
            f"DATABASE={self.database};UID={self.user};PWD={self.password};TDS_Version=5.0;"
        )

    def exec_sql(self, sql: str, *, database: str | None = None) -> tuple[int, bytes]:
        """Execute a SQL statement inside the Sybase ASE container via isql."""
        return exec_isql(
            self.container,
            sql,
            database=database or self.database,
            user=self.user,
            password=self.password,
        )

    def create_worker_database(self, db_name: str) -> None:
        """Create an isolated database inside the Sybase ASE container."""
        create_worker_database(
            self.container,
            db_name,
            user=self.user,
            password=self.password,
        )


def validate_sybase_database_name(db_name: str) -> str:
    """Validate that a Sybase database name conforms to ASE identifier limits.

    Args:
        db_name: Candidate Sybase database name.

    Returns:
        The validated database name.

    Raises:
        ValueError: If ``db_name`` exceeds length limits or has invalid characters.
    """
    if len(db_name) > SYBASE_MAX_DB_NAME_LENGTH or not _SYBASE_NAME_PATTERN.match(db_name):
        msg = (
            f"Invalid Sybase database name {db_name!r}: must start with a letter, contain only "
            f"ASCII letters, digits, or underscores, and be at most {SYBASE_MAX_DB_NAME_LENGTH} characters."
        )
        raise ValueError(msg)
    return db_name


def exec_isql(
    container: Container,
    sql: str,
    *,
    database: str = SYBASE_DATABASE,
    user: str = SYBASE_USER,
    password: str = SYBASE_PASSWORD,
) -> tuple[int, bytes]:
    """Execute a T-SQL batch inside a Sybase ASE container via the in-container CLI.

    Args:
        container: Running Sybase ASE container.
        sql: SQL statements to execute.
        database: Target database name.
        user: Login username.
        password: User password.

    Returns:
        Tuple of (exit_code, output_bytes).
    """
    batch = sql.strip()
    if not batch.endswith("go") and not batch.endswith("GO"):
        batch = f"{batch}\ngo"
    script = (
        f"for bin in {' '.join(ISQL_CANDIDATES)}; do "
        f"if command -v $bin >/dev/null 2>&1; then "
        f"$bin -U {shlex.quote(user)} -P {shlex.quote(password)} -D {shlex.quote(database)} -w 2048 <<'EOF'\n"
        f"{batch}\n"
        f"EOF\n"
        f"exit $?; "
        f"fi; "
        f"done; "
        f"exit 127"
    )
    result = container.exec_run(["sh", "-c", script])
    exit_code = result.exit_code if result.exit_code is not None else -1
    output = exec_output_to_bytes(result.output)
    return exit_code, output


def create_worker_database(
    container: Container,
    db_name: str,
    *,
    user: str = SYBASE_USER,
    password: str = SYBASE_PASSWORD,
) -> None:
    """Create a database inside the Sybase ASE container if it does not already exist.

    Args:
        container: Running Sybase container.
        db_name: Database name to create.
        user: Login username.
        password: User password.

    Raises:
        RuntimeError: If database creation fails.
    """
    valid_name = validate_sybase_database_name(db_name)
    sql = (
        f"IF NOT EXISTS (SELECT 1 FROM master.dbo.sysdatabases WHERE name = '{valid_name}')\n"
        f"BEGIN\n"
        f"    CREATE DATABASE {valid_name};\n"
        f"END\n"
    )
    exit_code, output = exec_isql(container, sql, database="master", user=user, password=password)
    if exit_code != 0:
        decoded = output.decode("utf-8", errors="replace").strip()
        msg = f"Failed to create Sybase database {valid_name!r} (exit {exit_code}): {decoded}"
        raise RuntimeError(msg)


def check_sybase_socket_ready(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check whether the Sybase ASE TCP port accepts connections without external drivers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


@contextmanager
def provide_sybase_service(
    container_service: ContainerService,
    sybase_image: str,
    sybase_user: str,
    sybase_password: str,
    sybase_database: str,
    sybase_startup_timeout: int,
    xdist_sybase_isolation_level: XdistIsolationLevel,
) -> Generator[SybaseService, None, None]:
    """Start and yield a ready SAP Sybase ASE service container.

    Yields:
        A configured SybaseService instance.
    """
    worker_num = get_xdist_worker_num()
    name = "sybase"
    initial_db = (
        validate_sybase_database_name(os.getenv("SYBASE_DATABASE", "pytestdb"))
        if worker_num is not None and xdist_sybase_isolation_level == "database"
        else sybase_database
    )
    if worker_num is not None and xdist_sybase_isolation_level == "server":
        name = f"sybase_{worker_num + 1}"

    def check(service: ServiceContainer) -> bool:
        if not check_sybase_socket_ready(service.host, service.port):
            return False
        try:
            logs = service.container.logs()
        except (OSError, RuntimeError, AttributeError):
            logs = b""
        if sybase_image == DEFAULT_SYBASE_IMAGE and b"SYBASE INITIALIZED" not in logs:
            return False
        code, out = exec_isql(
            service.container,
            "SELECT 1",
            database="master",
            user=sybase_user,
            password=sybase_password,
        )
        if code == 0:
            return True
        return b"1" in out

    with container_service.run(
        image=sybase_image,
        container_port=SYBASE_PORT,
        name=name,
        env={
            "SYBASE_PASSWORD": sybase_password,
            "SA_PASSWORD": sybase_password,
        },
        check=check,
        timeout=sybase_startup_timeout,
        pause=1.5,
        transient=xdist_sybase_isolation_level == "server",
    ) as service:
        if initial_db != "master":
            create_worker_database(
                service.container,
                initial_db,
                user=sybase_user,
                password=sybase_password,
            )
        yield SybaseService(
            container=service.container,
            host=service.host,
            port=service.port,
            user=sybase_user,
            password=sybase_password,
            database=initial_db,
        )


@pytest.fixture(scope="session")
def sybase_image() -> str:
    """Docker image tag for SAP Sybase ASE."""
    return os.getenv("SYBASE_IMAGE", DEFAULT_SYBASE_IMAGE)


@pytest.fixture(scope="session")
def sybase_user() -> str:
    """Username for authenticating with the Sybase ASE container."""
    return os.getenv("SYBASE_USER", SYBASE_USER)


@pytest.fixture(scope="session")
def sybase_password() -> str:
    """Password for authenticating with the Sybase ASE container."""
    return os.getenv("SYBASE_PASSWORD", SYBASE_PASSWORD)


@pytest.fixture(scope="session")
def sybase_database() -> str:
    """Initial database name on the Sybase ASE container."""
    return os.getenv("SYBASE_DATABASE", SYBASE_DATABASE)


@pytest.fixture(scope="session")
def sybase_startup_timeout() -> int:
    """Maximum seconds to wait for Sybase ASE container startup."""
    return int(os.getenv("SYBASE_STARTUP_TIMEOUT", "120"))


@pytest.fixture(scope="session")
def xdist_sybase_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for Sybase ASE."""
    return "database"


@pytest.fixture(scope="session")
def sybase_service(
    container_service: ContainerService,
    sybase_image: str,
    sybase_user: str,
    sybase_password: str,
    sybase_database: str,
    sybase_startup_timeout: int,
    xdist_sybase_isolation_level: XdistIsolationLevel,
) -> Generator[SybaseService, None, None]:
    """Provide a session-scoped Sybase ASE service container.

    Yields:
        A configured SybaseService instance.
    """
    with provide_sybase_service(
        container_service=container_service,
        sybase_image=sybase_image,
        sybase_user=sybase_user,
        sybase_password=sybase_password,
        sybase_database=sybase_database,
        sybase_startup_timeout=sybase_startup_timeout,
        xdist_sybase_isolation_level=xdist_sybase_isolation_level,
    ) as service:
        yield service
