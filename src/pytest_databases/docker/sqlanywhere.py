"""SAP SQL Anywhere container service fixtures."""

from __future__ import annotations

import ctypes
import dataclasses
import io
import os
import re
import shlex
import tarfile
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num, tcp_port_open
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
    "sqlanywhere_client_environment",
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
_SQLANYWHERE_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")
_READINESS_SQL = "SELECT 4242 AS probe; OUTPUT TO /dev/stdout"
_READINESS_ROW = "4242"
_DBCAPI_NAMES: tuple[str, ...] = (
    "libdbcapi_r.so",
    "libdbcapi_r.so.1",
    "libdbcapi.so",
    "libdbcapi_r.dylib",
    "dbcapi.dll",
)

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
    if len(db_name) > SQLANYWHERE_MAX_DB_NAME_LENGTH or not _SQLANYWHERE_NAME_PATTERN.fullmatch(db_name):
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
        f"*) \"$bin\" -nogui -c {quoted_conn} <<'EOF'\n"
        f"{batch}\n"
        "EOF\n"
        "rc=$?; if [ $rc -ne 126 ] && [ $rc -ne 127 ]; then exit $rc; fi ;; "
        "esac; "
        "fi; "
        "fi; "
        "done; "
        "exit 127"
    )
    result = container.exec_run(["sh", "-c", script])
    exit_code = result.exit_code if result.exit_code is not None else -1
    output = exec_output_to_bytes(result.output)
    return exit_code, output


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
    if xdist_sqlanywhere_isolation_level != "server":
        msg = (
            f"SQL Anywhere supports only 'server' xdist isolation, got {xdist_sqlanywhere_isolation_level!r}. "
            "Each worker starts its own container; override 'xdist_sqlanywhere_isolation_level' to return 'server'."
        )
        raise ValueError(msg)
    worker_num = get_xdist_worker_num()
    name = "sqlanywhere" if worker_num is None else f"sqlanywhere_{worker_num}"

    def check(service: ServiceContainer) -> bool:
        if not tcp_port_open(service.host, service.port, timeout=1.0):
            return False
        return _is_sqlanywhere_ready(
            *exec_dbisql(
                service.container,
                _READINESS_SQL,
                database=sqlanywhere_database,
                server_name=sqlanywhere_server,
                user=sqlanywhere_user,
                password=sqlanywhere_password,
            )
        )

    with container_service.run(
        image=sqlanywhere_image,
        container_port=SQLANYWHERE_PORT,
        name=name,
        env={
            "SQLANYWHERE_PASSWORD": sqlanywhere_password,
            "DBA_PASSWORD": sqlanywhere_password,
            "DATABASE_NAME": sqlanywhere_database,
            "SERVER_NAME": sqlanywhere_server,
        },
        check=check,
        timeout=sqlanywhere_startup_timeout,
        pause=1.0,
        transient=worker_num is not None,
    ) as service:
        yield SQLAnywhereService(
            container=service.container,
            host=service.host,
            port=service.port,
            user=sqlanywhere_user,
            password=sqlanywhere_password,
            database=sqlanywhere_database,
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


def extract_sqlanywhere_client_libs(
    container: Container,
    target_dir: Path,
    *,
    container_base_path: str | None = None,
    preload: bool = True,
) -> Path:
    """Extract native SAP SQL Anywhere client libraries from a container.

    Copies the ``lib64`` shared libraries and ``res`` message resources from the container. With ``preload`` the
    ``dbtasks``/``dblib`` dependencies and the ``dbcapi`` library are loaded into the current process with
    ``ctypes`` and ``RTLD_GLOBAL``, so a later load of ``dbcapi`` by name (for example by ``sqlanydb``) resolves to
    the extracted copy. The process environment is not modified; use :func:`sqlanywhere_client_environment` for the
    ``SQLANY16`` and ``SQLANY_API_DLL`` values.

    Args:
        container: Running SAP SQL Anywhere container.
        target_dir: Local destination directory to write extracted libraries into.
        container_base_path: Optional base directory in the container (auto-detected if None).
        preload: Whether to load the extracted libraries into the current process.

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

    if preload:
        lib_dir = _client_lib_dir(target_dir)
        for pattern in ("*dbtasks*", "*dblib*"):
            for dep in sorted(lib_dir.glob(pattern)):
                if dep.is_file() and not dep.name.endswith((".a", ".la")):
                    with suppress(OSError):
                        ctypes.CDLL(str(dep), mode=ctypes.RTLD_GLOBAL)
        api_dll = _find_dbcapi(lib_dir)
        if api_dll is not None and api_dll.is_file():
            with suppress(OSError):
                ctypes.CDLL(str(api_dll), mode=ctypes.RTLD_GLOBAL)

    return target_dir


def sqlanywhere_client_environment(target_dir: Path) -> dict[str, str]:
    """Return the environment variables that point SQL Anywhere clients at extracted libraries.

    Args:
        target_dir: Directory previously populated by :func:`extract_sqlanywhere_client_libs`.

    Returns:
        ``SQLANY16`` (the extraction directory) and, when a ``dbcapi`` library was extracted, ``SQLANY_API_DLL``.
    """
    environment = {"SQLANY16": str(target_dir)}
    api_dll = _find_dbcapi(_client_lib_dir(target_dir))
    if api_dll is not None:
        environment["SQLANY_API_DLL"] = str(api_dll)
    return environment


@pytest.fixture(scope="session")
def sqlanywhere_client_libs(
    sqlanywhere_service: SQLAnywhereService,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Path, None, None]:
    """Extract SAP SQL Anywhere native client libraries from the container.

    Copies native client libraries and message resources from the container, preloads them, and sets
    ``SQLANY16`` and ``SQLANY_API_DLL`` for driver packages such as ``sqlanydb``. The previous values of both
    variables are restored when the session ends.

    Args:
        sqlanywhere_service: Running SQL Anywhere container service.
        tmp_path_factory: Pytest session temporary directory factory.

    Yields:
        Path to directory containing the extracted client libraries and resources.
    """
    target_dir = extract_sqlanywhere_client_libs(
        sqlanywhere_service.container, tmp_path_factory.mktemp("sqlanywhere_client")
    )
    with pytest.MonkeyPatch.context() as patch:
        for key, value in sqlanywhere_client_environment(target_dir).items():
            patch.setenv(key, value)
        yield target_dir


def _is_sqlanywhere_ready(exit_code: int, output: bytes) -> bool:
    """Return whether ``dbisqlc`` output of the readiness query contains exactly the expected row.

    Args:
        exit_code: Exit code returned by ``exec_dbisql``.
        output: Output returned by ``exec_dbisql``.

    Returns:
        True when the query succeeded and one output line is exactly ``4242``.
    """
    if exit_code != 0:
        return False
    return any(line.strip() == _READINESS_ROW for line in output.decode("utf-8", errors="replace").splitlines())


def _extract_container_archive(container: Container, source_path: str, target_dir: Path) -> None:
    """Extract a directory tar archive from a container into a local directory.

    Members whose resolved path falls outside ``target_dir`` are skipped.
    """
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
            if not member_path.is_relative_to(resolved_target):
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


def _client_lib_dir(target_dir: Path) -> Path:
    """Return the extracted ``lib64`` directory, or ``target_dir`` when the archive had no ``lib64`` folder."""
    lib_dir = target_dir / "lib64"
    return lib_dir if lib_dir.exists() else target_dir


def _find_dbcapi(lib_dir: Path) -> Path | None:
    """Return the extracted ``dbcapi`` library, preferring the thread-safe ``libdbcapi_r`` build."""
    for name in _DBCAPI_NAMES:
        candidate = lib_dir / name
        if candidate.exists():
            return candidate
    return next(iter(sorted(lib_dir.glob("*dbcapi*"))), None)
