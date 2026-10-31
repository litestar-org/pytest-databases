"""SAP SQL Anywhere container service fixtures."""

from __future__ import annotations

import ctypes
import dataclasses
import io
import os
import re
import shlex
import socket
import tarfile
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

__all__ = (
    "DEFAULT_SQLANYWHERE_IMAGE",
    "SQLANYWHERE_CLIENT_CANDIDATE_PATHS",
    "SQLANYWHERE_DATABASE",
    "SQLANYWHERE_MAX_DB_NAME_LENGTH",
    "SQLANYWHERE_PASSWORD",
    "SQLANYWHERE_PORT",
    "SQLANYWHERE_SERVER",
    "SQLANYWHERE_USER",
    "SQLAnywhereService",
    "exec_dbisql",
    "extract_sqlanywhere_client_libs",
    "provide_sqlanywhere_service",
    "sqlanywhere_client_libs",
    "sqlanywhere_database",
    "sqlanywhere_image",
    "sqlanywhere_password",
    "sqlanywhere_server",
    "sqlanywhere_service",
    "sqlanywhere_startup_timeout",
    "sqlanywhere_user",
    "validate_sqlanywhere_database_name",
    "xdist_sqlanywhere_isolation_level",
)

DEFAULT_SQLANYWHERE_IMAGE = "jaschweder/sybase:latest"
SQLANYWHERE_PORT = 2638
SQLANYWHERE_USER = "dba"
SQLANYWHERE_PASSWORD = "sql"
SQLANYWHERE_DATABASE = "demo"
SQLANYWHERE_SERVER = "demo"
SQLANYWHERE_MAX_DB_NAME_LENGTH = 128
_SQLANYWHERE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")

SQLANYWHERE_CLIENT_CANDIDATE_PATHS: tuple[str, ...] = (
    "/opt/sqlanywhere16",
    "/opt/sqlanywhere17",
    "/opt/sybase",
)

DBISQL_CANDIDATES: tuple[str, ...] = (
    "/opt/sqlanywhere16/bin64/dbisqlc",
    "/opt/sqlanywhere17/bin64/dbisqlc",
    "dbisqlc",
    "/opt/sqlanywhere16/bin64/dbisql",
    "/opt/sqlanywhere17/bin64/dbisql",
    "dbisql",
)


@dataclasses.dataclass
class SQLAnywhereService(ServiceContainer):
    """Service handle for a running SAP SQL Anywhere container."""

    user: str
    password: str
    database: str
    server_name: str

    @property
    def connection_config(self) -> dict[str, str | int]:
        """Connection configuration parameters compatible with sqlanydb."""
        return {
            "uid": self.user,
            "pwd": self.password,
            "dbn": self.database,
            "eng": self.server_name,
            "host": f"{self.host}:{self.port}",
        }

    @property
    def dsn(self) -> str:
        """ODBC/dbisql connection string representation."""
        return (
            f"UID={self.user};PWD={self.password};DBN={self.database};"
            f"ENG={self.server_name};LINKS=tcpip(host={self.host};port={self.port});"
        )

    def exec_sql(self, sql: str, *, database: str | None = None) -> tuple[int, bytes]:
        """Execute a SQL statement inside the SQL Anywhere container via dbisql."""
        return exec_dbisql(
            self.container,
            sql,
            database=database or self.database,
            server_name=self.server_name,
            user=self.user,
            password=self.password,
        )


def validate_sqlanywhere_database_name(db_name: str) -> str:
    """Validate that a SQL Anywhere database name conforms to identifier rules.

    Args:
        db_name: Candidate database name.

    Returns:
        The validated database name.

    Raises:
        ValueError: If ``db_name`` exceeds length limits or has invalid characters.
    """
    if len(db_name) > SQLANYWHERE_MAX_DB_NAME_LENGTH or not _SQLANYWHERE_NAME_PATTERN.match(db_name):
        msg = (
            f"Invalid SQL Anywhere database name {db_name!r}: must start with a letter, contain only "
            f"ASCII letters, digits, or underscores, and be at most {SQLANYWHERE_MAX_DB_NAME_LENGTH} characters."
        )
        raise ValueError(msg)
    return db_name


def exec_dbisql(
    container: Container,
    sql: str,
    *,
    database: str = SQLANYWHERE_DATABASE,
    server_name: str = SQLANYWHERE_SERVER,
    user: str = SQLANYWHERE_USER,
    password: str = SQLANYWHERE_PASSWORD,
    port: int = SQLANYWHERE_PORT,
) -> tuple[int, bytes]:
    """Execute SQL statements inside a SQL Anywhere container using the in-container CLI.

    Args:
        container: Running SQL Anywhere container.
        sql: SQL statements to execute.
        database: Database name to connect to.
        server_name: Database engine server name.
        user: Login username.
        password: User password.
        port: Container internal TCP port.

    Returns:
        Tuple of (exit_code, output_bytes).
    """
    batch = sql.strip()
    if not batch.endswith(";"):
        batch = f"{batch};"
    conn_str = f"UID={user};PWD={password};DBN={database};ENG={server_name};LINKS=tcpip(host=127.0.0.1;port={port})"
    quoted_conn = shlex.quote(conn_str)
    quoted_batch = shlex.quote(batch)
    script = (
        "chmod +x /opt/sqlanywhere16/bin64/* /opt/sqlanywhere17/bin64/* 2>/dev/null || true; "
        f"for bin in {' '.join(DBISQL_CANDIDATES)}; do "
        'if [ -f "$bin" ] || command -v "$bin" >/dev/null 2>&1; then '
        'chmod +x "$bin" 2>/dev/null || true; '
        'if [ -x "$bin" ] || command -v "$bin" >/dev/null 2>&1; then '
        'case "$bin" in '
        f'*dbisqlc) "$bin" -q -c {quoted_conn} {quoted_batch}; rc=$?; if [ $rc -ne 126 ] && [ $rc -ne 127 ]; then exit $rc; fi ;; '
        f'*) "$bin" -nogui -c {quoted_conn} <<\'EOF\'\n'
        f'{batch}\n'
        'EOF\n'
        'rc=$?; if [ $rc -ne 126 ] && [ $rc -ne 127 ]; then exit $rc; fi ;; '
        'esac; '
        'fi; '
        'fi; '
        'done; '
        'exit 127'
    )
    result = container.exec_run(["sh", "-c", script])
    exit_code = result.exit_code if result.exit_code is not None else -1
    output = exec_output_to_bytes(result.output)
    return exit_code, output


def check_sqlanywhere_socket_ready(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check whether the SQL Anywhere TCP port accepts connections without external drivers."""
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
def provide_sqlanywhere_service(
    container_service: ContainerService,
    sqlanywhere_image: str,
    sqlanywhere_user: str,
    sqlanywhere_password: str,
    sqlanywhere_database: str,
    sqlanywhere_server: str,
    sqlanywhere_startup_timeout: int,
    xdist_sqlanywhere_isolation_level: XdistIsolationLevel,
) -> Generator[SQLAnywhereService, None, None]:
    """Start and yield a ready SAP SQL Anywhere service container.

    Yields:
        A configured SQLAnywhereService instance.
    """
    worker_num = get_xdist_worker_num()
    name = "sqlanywhere"
    initial_db = (
        validate_sqlanywhere_database_name(os.getenv("SQLANYWHERE_DATABASE", "pytestdb"))
        if worker_num is not None and xdist_sqlanywhere_isolation_level == "database"
        else sqlanywhere_database
    )
    if worker_num is not None and xdist_sqlanywhere_isolation_level == "server":
        name = f"sqlanywhere_{worker_num + 1}"

    def check(service: ServiceContainer) -> bool:
        if not check_sqlanywhere_socket_ready(service.host, service.port):
            return False
        code, out = exec_dbisql(
            service.container,
            "SELECT 1",
            database=initial_db,
            server_name=sqlanywhere_server,
            user=sqlanywhere_user,
            password=sqlanywhere_password,
        )
        if code == 0:
            return True
        return b"1" in out

    with container_service.run(
        image=sqlanywhere_image,
        container_port=SQLANYWHERE_PORT,
        name=name,
        env={
            "SQLANYWHERE_PASSWORD": sqlanywhere_password,
            "DBA_PASSWORD": sqlanywhere_password,
            "DATABASE_NAME": initial_db,
            "SERVER_NAME": sqlanywhere_server,
        },
        check=check,
        timeout=sqlanywhere_startup_timeout,
        pause=1.0,
        transient=xdist_sqlanywhere_isolation_level == "server",
    ) as service:
        yield SQLAnywhereService(
            container=service.container,
            host=service.host,
            port=service.port,
            user=sqlanywhere_user,
            password=sqlanywhere_password,
            database=initial_db,
            server_name=sqlanywhere_server,
        )


@pytest.fixture(scope="session")
def sqlanywhere_image() -> str:
    """Docker image tag for SAP SQL Anywhere."""
    return os.getenv("SQLANYWHERE_IMAGE", DEFAULT_SQLANYWHERE_IMAGE)


@pytest.fixture(scope="session")
def sqlanywhere_user() -> str:
    """Username for authenticating with the SQL Anywhere container."""
    return os.getenv("SQLANYWHERE_USER", SQLANYWHERE_USER)


@pytest.fixture(scope="session")
def sqlanywhere_password() -> str:
    """Password for authenticating with the SQL Anywhere container."""
    return os.getenv("SQLANYWHERE_PASSWORD", SQLANYWHERE_PASSWORD)


@pytest.fixture(scope="session")
def sqlanywhere_database() -> str:
    """Database name on the SQL Anywhere container."""
    return os.getenv("SQLANYWHERE_DATABASE", SQLANYWHERE_DATABASE)


@pytest.fixture(scope="session")
def sqlanywhere_server() -> str:
    """Server/engine name on the SQL Anywhere container."""
    return os.getenv("SQLANYWHERE_SERVER", SQLANYWHERE_SERVER)


@pytest.fixture(scope="session")
def sqlanywhere_startup_timeout() -> int:
    """Maximum seconds to wait for SQL Anywhere container startup."""
    return int(os.getenv("SQLANYWHERE_STARTUP_TIMEOUT", "60"))


@pytest.fixture(scope="session")
def xdist_sqlanywhere_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for SQL Anywhere."""
    return "server"


@pytest.fixture(scope="session")
def sqlanywhere_service(
    container_service: ContainerService,
    sqlanywhere_image: str,
    sqlanywhere_user: str,
    sqlanywhere_password: str,
    sqlanywhere_database: str,
    sqlanywhere_server: str,
    sqlanywhere_startup_timeout: int,
    xdist_sqlanywhere_isolation_level: XdistIsolationLevel,
) -> Generator[SQLAnywhereService, None, None]:
    """Provide a session-scoped SQL Anywhere service container.

    Yields:
        A configured SQLAnywhereService instance.
    """
    with provide_sqlanywhere_service(
        container_service=container_service,
        sqlanywhere_image=sqlanywhere_image,
        sqlanywhere_user=sqlanywhere_user,
        sqlanywhere_password=sqlanywhere_password,
        sqlanywhere_database=sqlanywhere_database,
        sqlanywhere_server=sqlanywhere_server,
        sqlanywhere_startup_timeout=sqlanywhere_startup_timeout,
        xdist_sqlanywhere_isolation_level=xdist_sqlanywhere_isolation_level,
    ) as service:
        yield service


def _extract_container_archive(container: Container, source_path: str, target_dir: Path) -> None:
    """Extract a directory tar archive from a container into a local directory."""
    try:
        bits, _stat = container.get_archive(source_path)
    except (OSError, RuntimeError, AttributeError):
        return
    archive_bytes = b"".join(bits)
    if not archive_bytes:
        return
    resolved_target = target_dir.resolve()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
        for member in tar.getmembers():
            member_path = (target_dir / member.name).resolve()
            if not str(member_path).startswith(str(resolved_target)):
                continue
            if member.isdir():
                member_path.mkdir(parents=True, exist_ok=True)
            elif member.issym():
                with suppress(OSError):
                    member_path.unlink(missing_ok=True)
                    member_path.symlink_to(member.linkname)
            elif member.isfile():
                extracted = tar.extractfile(member)
                if extracted is not None:
                    member_path.parent.mkdir(parents=True, exist_ok=True)
                    member_path.write_bytes(extracted.read())


def extract_sqlanywhere_client_libs(
    container: Container,
    target_dir: Path,
    *,
    container_base_path: str | None = None,
    preload: bool = True,
) -> Path:
    """Extract native SAP SQL Anywhere client libraries from a container.

    Copies shared libraries and language message resources from the container,
    preloads dependent shared libraries via ctypes with RTLD_GLOBAL, and registers
    SQLANY16 and SQLANY_API_DLL environment variables for client drivers like sqlanydb.

    Args:
        container: Running SAP SQL Anywhere container.
        target_dir: Local destination directory to write extracted libraries into.
        container_base_path: Optional base directory in the container (auto-detected if None).
        preload: Whether to load libraries into process address space and set env vars.

    Returns:
        The target directory containing extracted client libraries.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    base_path = container_base_path
    if base_path is None:
        base_path = "/opt/sqlanywhere16"
        for candidate in SQLANYWHERE_CLIENT_CANDIDATE_PATHS:
            with suppress(OSError, RuntimeError, AttributeError):
                res = container.exec_run(["test", "-d", f"{candidate}/lib64"])
                if res.exit_code == 0:
                    base_path = candidate
                    break

    for sub_dir in ("lib64", "res"):
        _extract_container_archive(container, f"{base_path}/{sub_dir}", target_dir)

    lib_dir = target_dir / "lib64"
    if not lib_dir.exists():
        lib_dir = target_dir

    api_dll: Path | None = None
    for name in ("libdbcapi_r.so", "libdbcapi_r.so.1", "libdbcapi.so", "libdbcapi_r.dylib", "dbcapi.dll"):
        dll_candidate = lib_dir / name
        if dll_candidate.exists():
            api_dll = dll_candidate
            break
    if api_dll is None:
        candidates = sorted(lib_dir.glob("*dbcapi*"))
        if candidates:
            api_dll = candidates[0]

    if preload:
        os.environ["SQLANY16"] = str(target_dir)
        if api_dll is not None:
            os.environ["SQLANY_API_DLL"] = str(api_dll)

        current_ld = os.getenv("LD_LIBRARY_PATH", "")
        if str(lib_dir) not in current_ld.split(":"):
            os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{current_ld}" if current_ld else str(lib_dir)

        for pattern in ("*dbtasks*", "*dblib*"):
            for dep in sorted(lib_dir.glob(pattern)):
                if dep.is_file() and not dep.name.endswith((".a", ".la")):
                    with suppress(OSError):
                        ctypes.CDLL(str(dep), mode=ctypes.RTLD_GLOBAL)
        if api_dll is not None and api_dll.is_file():
            with suppress(OSError):
                ctypes.CDLL(str(api_dll), mode=ctypes.RTLD_GLOBAL)

    return target_dir


@pytest.fixture(scope="session")
def sqlanywhere_client_libs(
    sqlanywhere_service: SQLAnywhereService,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Extract SAP SQL Anywhere native client libraries from the container.

    Copies native client libraries and message resources from the container,
    preloads dependent shared libraries, and configures SQLANY16 and SQLANY_API_DLL
    environment variables for driver packages such as sqlanydb.

    Args:
        sqlanywhere_service: Running SQL Anywhere container service.
        tmp_path_factory: Pytest session temporary directory factory.

    Returns:
        Path to directory containing the extracted client libraries and resources.
    """
    target_dir = tmp_path_factory.mktemp("sqlanywhere_client")
    return extract_sqlanywhere_client_libs(sqlanywhere_service.container, target_dir)
