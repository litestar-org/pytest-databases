"""Oracle Database and Autonomous Database Free container fixtures and wallet helpers."""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import re
import shlex
import tarfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases._service import ContainerService
from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "DEFAULT_ORACLE_ADB_IMAGE",
    "ORACLE_ADB_ADW_SERVICES",
    "ORACLE_ADB_ATP_SERVICES",
    "ORACLE_PASSWORD",
    "ORACLE_SYSTEM_PASSWORD",
    "ORACLE_USER",
    "OracleADBService",
    "OracleService",
    "ensure_oracle_user",
    "extract_adb_wallet",
    "open_oracle_connection",
    "oracle_18c_connection",
    "oracle_18c_image",
    "oracle_18c_service",
    "oracle_18c_service_name",
    "oracle_23ai_connection",
    "oracle_23ai_image",
    "oracle_23ai_service",
    "oracle_23ai_service_name",
    "oracle_adb_hostname",
    "oracle_adb_image",
    "oracle_adb_service",
    "oracle_adb_wallet_password",
    "oracle_adb_workload_type",
    "oracle_connection",
    "oracle_password",
    "oracle_responsive",
    "oracle_service",
    "oracle_startup_connection",
    "oracle_system_password",
    "oracle_user",
    "parse_tnsnames",
    "provide_oracle_adb_service",
    "provide_oracle_service",
    "rewrite_tnsnames",
    "xdist_oracle_isolation_level",
]

ORACLE_USER = "app"
ORACLE_PASSWORD = "super-secret"
ORACLE_SYSTEM_PASSWORD = "super-secret"
DEFAULT_ORACLE_ADB_IMAGE = "container-registry.oracle.com/database/adb-free:latest-23ai"
DEFAULT_ORACLE_ADB_WALLET_PATH = "/u01/app/oracle/wallets/tls_wallet"
ORACLE_ADB_ATP_SERVICES: tuple[str, ...] = (
    "myatp_high",
    "myatp_medium",
    "myatp_low",
    "myatp_tp",
    "myatp_tpurgent",
)
ORACLE_ADB_ADW_SERVICES: tuple[str, ...] = (
    "myadw_high",
    "myadw_medium",
    "myadw_low",
)
_TNS_ENTRY_REGEX = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(\(DESCRIPTION\s*=.*?(?=\n\s*[A-Za-z0-9_.-]+\s*=\s*\(DESCRIPTION|\Z))",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)
_TNS_PARAM_PATTERNS: dict[str, re.Pattern[str]] = {
    "protocol": re.compile(r"\(\s*PROTOCOL\s*=\s*([A-Za-z0-9_.-]+)\s*\)", re.IGNORECASE),
    "host": re.compile(r"\(\s*HOST\s*=\s*([^)\s]+)\s*\)", re.IGNORECASE),
    "port": re.compile(r"\(\s*PORT\s*=\s*(\d+)\s*\)", re.IGNORECASE),
    "service_name": re.compile(r"\(\s*SERVICE_NAME\s*=\s*([^)\s]+)\s*\)", re.IGNORECASE),
}


@dataclass
class OracleService(ServiceContainer):
    """Container handle with administrative and application credentials for Oracle."""

    user: str
    password: str
    system_password: str
    service_name: str


@dataclass
class OracleADBService(OracleService):
    """Container handle for Oracle Autonomous Database Free with TLS/mTLS wallet support."""

    tls_port: int
    wallet_password: str
    workload_type: str
    service_names: tuple[str, ...]

    def extract_wallet(self, target_dir: Path) -> Path:
        """Extract the container wallet files into ``target_dir`` and rewrite ``tnsnames.ora``."""
        return extract_adb_wallet(
            self.container,
            target_dir,
            host=self.host,
            port=self.port,
            tls_port=self.tls_port,
        )


def oracle_responsive(host: str, port: int, service_name: str, user: str, password: str) -> bool:
    """Check whether an Oracle instance responds to a ``SELECT 1 FROM dual`` query via ``oracledb``.

    .. deprecated:: 0.20.0
        ``oracle_responsive`` is deprecated and will be removed in v1.0.

    Returns:
        True when the query returns ``1``, otherwise False.
    """
    warnings.warn(
        "`oracle_responsive` is deprecated and will be removed in v1.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    oracledb = _load_oracledb()
    db_error = getattr(oracledb, "Error", OSError)
    try:
        conn = oracledb.connect(
            host=host,
            port=port,
            user=user,
            service_name=service_name,
            password=password,
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM dual")
            resp = cursor.fetchone()
        return resp[0] == 1 if resp is not None else False
    except (OSError, RuntimeError, ValueError, db_error):
        return False


def parse_tnsnames(tns_content: str) -> dict[str, dict[str, str]]:
    """Parse an Oracle ``tnsnames.ora`` file into structured service descriptor dictionaries.

    Args:
        tns_content: Raw text content of ``tnsnames.ora``.

    Returns:
        Mapping of lowercase TNS alias names to dictionaries containing ``protocol``,
        ``host``, ``port``, ``service_name``, and ``descriptor``.
    """
    parsed: dict[str, dict[str, str]] = {}
    for match in _TNS_ENTRY_REGEX.finditer(tns_content):
        alias = match.group(1).strip().lower()
        descriptor = " ".join(match.group(2).split())
        entry: dict[str, str] = {"descriptor": descriptor}
        for key, pattern in _TNS_PARAM_PATTERNS.items():
            param_match = pattern.search(descriptor)
            if param_match:
                entry[key] = param_match.group(1)
        parsed[alias] = entry
    return parsed


def rewrite_tnsnames(
    tns_content: str,
    *,
    host: str,
    port: int,
    tls_port: int | None = None,
) -> str:
    """Rewrite ``HOST`` and ``PORT`` entries in ``tnsnames.ora`` to match mapped container ports.

    Args:
        tns_content: Original ``tnsnames.ora`` content.
        host: Mapped host address.
        port: Mapped host port for internal port 1521.
        tls_port: Optional mapped host port for internal mTLS port 1522.

    Returns:
        Updated ``tnsnames.ora`` text.
    """
    updated = re.sub(r"(\(\s*HOST\s*=\s*)[^)\s]+(\s*\))", rf"\g<1>{host}\2", tns_content, flags=re.IGNORECASE)
    updated = re.sub(r"(\(\s*PORT\s*=\s*)1521(\s*\))", rf"\g<1>{port}\2", updated, flags=re.IGNORECASE)
    if tls_port is not None:
        updated = re.sub(r"(\(\s*PORT\s*=\s*)1522(\s*\))", rf"\g<1>{tls_port}\2", updated, flags=re.IGNORECASE)
    return updated


def extract_adb_wallet(
    container: Container,
    target_dir: Path,
    *,
    host: str,
    port: int,
    tls_port: int | None = None,
    container_wallet_path: str = DEFAULT_ORACLE_ADB_WALLET_PATH,
) -> Path:
    """Extract the TLS/mTLS wallet directory from an Oracle ADB-Free container and rewrite ``tnsnames.ora``.

    Args:
        container: Running Oracle ADB-Free container.
        target_dir: Destination host directory where wallet files will be written.
        host: Mapped container host address.
        port: Mapped port for internal port 1521.
        tls_port: Optional mapped port for internal port 1522.
        container_wallet_path: Path to the wallet directory inside the container.

    Returns:
        Path to ``target_dir`` containing extracted wallet files (``cwallet.sso``, ``ewallet.pem``,
        ``tnsnames.ora``, ``sqlnet.ora``).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    bits, _stat = container.get_archive(container_wallet_path)
    archive_bytes = b"".join(bits)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            filename = Path(member.name).name
            if not filename or filename.startswith("."):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            dest_file = target_dir / filename
            if filename.lower() == "tnsnames.ora":
                text = data.decode("utf-8", errors="replace")
                rewritten = rewrite_tnsnames(text, host=host, port=port, tls_port=tls_port)
                dest_file.write_text(rewritten, encoding="utf-8")
            else:
                dest_file.write_bytes(data)
    return target_dir


def ensure_oracle_user(
    container: Container,
    user: str,
    password: str,
    service_name: str,
    system_password: str,
) -> bool:
    """Ensure an Oracle application user exists with appropriate tablespace quota and roles.

    Args:
        container: The container instance.
        user: Effective username to create.
        password: User password.
        service_name: Oracle service or PDB name.
        system_password: SYS administrative user password.

    Returns:
        ``True`` if the SQL*Plus provisioning command exited cleanly.
    """
    setup_script = "\n".join([
        f'CREATE USER {user} IDENTIFIED BY "{password}";',
        f"GRANT CONNECT, RESOURCE, DBA TO {user};",
        f"ALTER USER {user} QUOTA UNLIMITED ON USERS;",
    ])
    exit_code, _ = _exec_sqlplus(
        container,
        user="sys",
        password=system_password,
        service_name=service_name,
        sql=setup_script,
        as_sysdba=True,
        whenever_sqlerror="CONTINUE",
    )
    return exit_code == 0


@contextlib.contextmanager
def provide_oracle_service(
    docker_service: DockerService,
    image: str,
    name: str,
    service_name: str,
    user: str,
    password: str,
    system_password: str,
    isolation_level: XdistIsolationLevel = "database",
) -> Generator[OracleService, None, None]:
    """Start and manage an Oracle database container with schema or server isolation.

    Args:
        docker_service: The container service manager.
        image: Container image for Oracle.
        name: Logical container service name.
        service_name: Oracle PDB or service name.
        user: Default application username.
        password: Application user password.
        system_password: Administrative SYS password.
        isolation_level: xdist isolation strategy (database or server).

    Yields:
        An OracleService handle configured for the active worker.
    """
    worker_num = get_xdist_worker_num()
    effective_user = user
    if worker_num is not None:
        if isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            effective_user = f"{user}_{worker_num}"

    user_provisioned = False

    def check(_service: ServiceContainer) -> bool:
        nonlocal user_provisioned
        if effective_user != user and not user_provisioned:
            sys_exit, sys_out = _exec_sqlplus(
                _service.container,
                user="sys",
                password=system_password,
                service_name=service_name,
                sql="SELECT 1 FROM dual",
                as_sysdba=True,
            )
            if sys_exit != 0 or sys_out.strip() != b"1":
                return False
            if (
                ensure_oracle_user(
                    _service.container,
                    user=effective_user,
                    password=password,
                    service_name=service_name,
                    system_password=system_password,
                )
                is False
            ):
                return False
            user_provisioned = True
        exit_code, output = _exec_sqlplus(
            _service.container,
            effective_user,
            password,
            service_name,
            "SELECT 1 FROM dual",
        )
        return exit_code == 0 and output.strip() == b"1"

    with docker_service.run(
        image=image,
        name=name,
        check=check,
        container_port=1521,
        timeout=60,
        transient=worker_num is not None and isolation_level == "server",
        env={
            "ORACLE_PASSWORD": system_password,
            "APP_USER_PASSWORD": password,
            "APP_USER": user,
        },
    ) as service:
        yield OracleService(
            host=service.host,
            port=service.port,
            container=service.container,
            system_password=system_password,
            user=effective_user,
            password=password,
            service_name=service_name,
        )


@contextlib.contextmanager
def provide_oracle_adb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    workload_type: str,
    hostname: str,
    user: str,
    password: str,
    system_password: str,
    wallet_password: str,
    isolation_level: XdistIsolationLevel = "database",
) -> Generator[OracleADBService, None, None]:
    """Start and manage an Oracle Autonomous Database Free (23ai) container.

    Args:
        docker_service: The container service manager.
        image: Oracle ADB-Free container image.
        name: Logical container service name.
        workload_type: Autonomous workload profile (``ATP`` or ``ADW``).
        hostname: Container hostname required by ADB-Free initialization scripts.
        user: Default application username.
        password: Application user password.
        system_password: ADMIN / SYS password.
        wallet_password: Password protecting the container's TLS/mTLS wallet.
        isolation_level: xdist isolation strategy (database or server).

    Yields:
        An OracleADBService handle configured for the active worker.
    """
    normalized_workload = workload_type.strip().upper()
    service_names = ORACLE_ADB_ADW_SERVICES if normalized_workload == "ADW" else ORACLE_ADB_ATP_SERVICES
    default_service_name = f"{service_names[0]}.adb.oraclecloud.com"

    worker_num = get_xdist_worker_num()
    effective_user = user
    if worker_num is not None:
        if isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            effective_user = f"{user}_{worker_num}"

    user_provisioned = False

    def check(_service: ServiceContainer) -> bool:
        nonlocal user_provisioned
        if not user_provisioned:
            sys_exit, sys_out = _exec_sqlplus(
                _service.container,
                user="sys",
                password=system_password,
                service_name=default_service_name,
                sql="SELECT 1 FROM dual",
                as_sysdba=True,
            )
            if sys_exit != 0 or sys_out.strip() != b"1":
                return False
            if (
                ensure_oracle_user(
                    _service.container,
                    user=effective_user,
                    password=password,
                    service_name=default_service_name,
                    system_password=system_password,
                )
                is False
            ):
                return False
            user_provisioned = True
        exit_code, output = _exec_sqlplus(
            _service.container,
            effective_user,
            password,
            default_service_name,
            "SELECT 1 FROM dual",
        )
        return exit_code == 0 and output.strip() == b"1"

    devices = ["/dev/fuse"] if Path("/dev/fuse").exists() else None
    with docker_service.run(
        image=image,
        name=name,
        check=check,
        container_port=1521,
        extra_ports={1522: None},
        timeout=300,
        pause=2.0,
        transient=worker_num is not None and isolation_level == "server",
        hostname=hostname,
        cap_add=["SYS_ADMIN"],
        devices=devices,
        env={
            "WORKLOAD_TYPE": normalized_workload,
            "WALLET_PASSWORD": wallet_password,
            "ADMIN_PASSWORD": system_password,
        },
    ) as service:
        tls_port = ContainerService.resolve_port(service.container, 1522)
        yield OracleADBService(
            host=service.host,
            port=service.port,
            tls_port=tls_port,
            container=service.container,
            system_password=system_password,
            user=effective_user,
            password=password,
            service_name=default_service_name,
            wallet_password=wallet_password,
            workload_type=normalized_workload,
            service_names=service_names,
        )


@contextlib.contextmanager
def open_oracle_connection(
    service: OracleService,
    fixture_name: str = "open_oracle_connection",
) -> Generator[Any, None, None]:
    """Open and yield a deprecated ``oracledb`` connection for ``service``.

    Yields:
        An open ``oracledb.Connection``.
    """
    warnings.warn(
        f"`{fixture_name}` is deprecated and will be removed in v1.0. "
        "Create an `oracledb` connection from `oracle_service` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    oracledb = _load_oracledb()
    with oracledb.connect(
        host=service.host,
        port=service.port,
        user=service.user,
        service_name=service.service_name,
        password=service.password,
    ) as db_connection:
        yield db_connection


@pytest.fixture(scope="session")
def xdist_oracle_isolation_level() -> XdistIsolationLevel:
    """Determine Oracle xdist isolation mode (database or server).

    Returns:
        The isolation mode string.
    """
    return "database"


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_image() -> str:
    """Container image for Oracle Database 23ai Free.

    Returns:
        The container image tag.
    """
    return "gvenzl/oracle-free:23-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service_name() -> str:
    """Default PDB service name for Oracle Database 23ai Free.

    Returns:
        The pluggable database name.
    """
    return "FREEPDB1"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_image() -> str:
    """Container image for Oracle Database 18c XE.

    Returns:
        The container image tag.
    """
    return "gvenzl/oracle-xe:18-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service_name() -> str:
    """Default PDB service name for Oracle Database 18c XE.

    Returns:
        The pluggable database name.
    """
    return "xepdb1"


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_image() -> str:
    """Container image for Oracle Autonomous Database Free (23ai)."""
    return os.getenv("ORACLE_ADB_IMAGE", DEFAULT_ORACLE_ADB_IMAGE)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_workload_type() -> str:
    """Workload type for Oracle Autonomous Database Free (``ATP`` or ``ADW``)."""
    return os.getenv("ORACLE_ADB_WORKLOAD_TYPE", "ATP")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_hostname() -> str:
    """Container hostname for Oracle Autonomous Database Free."""
    return os.getenv("ORACLE_ADB_HOSTNAME", "adb-free.local")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_wallet_password() -> str:
    """Wallet password for Oracle Autonomous Database Free."""
    return os.getenv("ORACLE_ADB_WALLET_PASSWORD", "Welcome12345!")


@pytest.fixture(autouse=False, scope="session")
def oracle_user() -> str:
    """Default application username for Oracle.

    Returns:
        The default username.
    """
    return ORACLE_USER


@pytest.fixture(autouse=False, scope="session")
def oracle_password() -> str:
    """Default application password for Oracle.

    Returns:
        The default password.
    """
    return ORACLE_PASSWORD


@pytest.fixture(autouse=False, scope="session")
def oracle_system_password() -> str:
    """Default administrative SYS password for Oracle.

    Returns:
        The administrative password.
    """
    return ORACLE_SYSTEM_PASSWORD


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service(
    docker_service: DockerService,
    xdist_oracle_isolation_level: XdistIsolationLevel,
    oracle_23ai_image: str,
    oracle_23ai_service_name: str,
    oracle_user: str,
    oracle_password: str,
    oracle_system_password: str,
) -> Generator[OracleService, None, None]:
    """Session fixture providing an Oracle Database 23ai Free container service.

    Args:
        docker_service: Container manager.
        xdist_oracle_isolation_level: Isolation mode for xdist workers.
        oracle_23ai_image: Container image.
        oracle_23ai_service_name: Pluggable database name.
        oracle_user: Application username.
        oracle_password: Application password.
        oracle_system_password: Administrative SYS password.

    Yields:
        An OracleService handle.
    """
    with provide_oracle_service(
        image=oracle_23ai_image,
        name="oracle23ai",
        service_name=oracle_23ai_service_name,
        user=oracle_user,
        password=oracle_password,
        system_password=oracle_system_password,
        docker_service=docker_service,
        isolation_level=xdist_oracle_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service(
    docker_service: DockerService,
    xdist_oracle_isolation_level: XdistIsolationLevel,
    oracle_18c_image: str,
    oracle_18c_service_name: str,
    oracle_user: str,
    oracle_password: str,
    oracle_system_password: str,
) -> Generator[OracleService, None, None]:
    """Session fixture providing an Oracle Database 18c XE container service.

    Args:
        docker_service: Container manager.
        xdist_oracle_isolation_level: Isolation mode for xdist workers.
        oracle_18c_image: Container image.
        oracle_18c_service_name: Pluggable database name.
        oracle_user: Application username.
        oracle_password: Application password.
        oracle_system_password: Administrative SYS password.

    Yields:
        An OracleService handle.
    """
    with provide_oracle_service(
        image=oracle_18c_image,
        name="oracle18c",
        service_name=oracle_18c_service_name,
        user=oracle_user,
        password=oracle_password,
        system_password=oracle_system_password,
        docker_service=docker_service,
        isolation_level=xdist_oracle_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_service(
    docker_service: DockerService,
    xdist_oracle_isolation_level: XdistIsolationLevel,
    oracle_adb_image: str,
    oracle_adb_workload_type: str,
    oracle_adb_hostname: str,
    oracle_user: str,
    oracle_password: str,
    oracle_system_password: str,
    oracle_adb_wallet_password: str,
) -> Generator[OracleADBService, None, None]:
    """Session fixture providing an Oracle Autonomous Database Free (23ai) container service.

    Yields:
        An OracleADBService handle.
    """
    with provide_oracle_adb_service(
        docker_service=docker_service,
        image=oracle_adb_image,
        name="oracle_adb",
        workload_type=oracle_adb_workload_type,
        hostname=oracle_adb_hostname,
        user=oracle_user,
        password=oracle_password,
        system_password=oracle_system_password,
        wallet_password=oracle_adb_wallet_password,
        isolation_level=xdist_oracle_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_service(oracle_23ai_service: OracleService) -> OracleService:
    """Alias for the latest default Oracle service (23ai).

    Args:
        oracle_23ai_service: The Oracle 23ai service instance.

    Returns:
        The Oracle 23ai service instance.
    """
    return oracle_23ai_service


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_connection(oracle_18c_service: OracleService) -> Generator[Any, None, None]:
    """Deprecated ``oracledb`` connection fixture for Oracle 18c XE.

    Yields:
        An open ``oracledb.Connection``.
    """
    with open_oracle_connection(oracle_18c_service, "oracle_18c_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_connection(oracle_23ai_service: OracleService) -> Generator[Any, None, None]:
    """Deprecated ``oracledb`` connection fixture for Oracle 23ai Free.

    Yields:
        An open ``oracledb.Connection``.
    """
    with open_oracle_connection(oracle_23ai_service, "oracle_23ai_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def oracle_connection(oracle_23ai_connection: Any) -> Any:
    """Deprecated alias for ``oracle_23ai_connection``.

    Returns:
        The active ``oracle_23ai_connection`` instance.
    """
    warnings.warn(
        "`oracle_connection` is deprecated and will be removed in v1.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    return oracle_23ai_connection


@pytest.fixture(autouse=False, scope="session")
def oracle_startup_connection(oracle_23ai_connection: Any) -> Any:
    """Deprecated alias for ``oracle_23ai_connection`` preserved for v0.19.0 callers.

    Returns:
        The active ``oracle_23ai_connection`` instance.
    """
    warnings.warn(
        "`oracle_startup_connection` is deprecated and will be removed in v1.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    return oracle_23ai_connection


def _load_oracledb() -> Any:
    """Import ``oracledb`` lazily for deprecated connection fixtures.

    Returns:
        Imported ``oracledb`` module.

    Raises:
        pytest.UsageError: If ``oracledb`` is not installed.
    """
    try:
        return importlib.import_module("oracledb")
    except ModuleNotFoundError as exc:
        msg = "Oracle connection fixtures require the 'oracledb' package (`pip install pytest-databases[oracle]`)."
        raise pytest.UsageError(msg) from exc


def _normalize_sqlplus_statement(sql: str) -> str:
    """Ensure a SQL statement terminates with a semicolon for SQL*Plus.

    Args:
        sql: The input SQL string.

    Returns:
        Semicolon-terminated statement.
    """
    statement = sql.strip()
    if not statement.endswith(";"):
        statement = f"{statement};"
    return statement


def _exec_sqlplus(
    container: Container,
    user: str,
    password: str,
    service_name: str,
    sql: str,
    as_sysdba: bool = False,
    whenever_sqlerror: str = "EXIT SQL.SQLCODE",
) -> tuple[int, bytes]:
    """Execute SQL statement or script inside Oracle container via sqlplus.

    Args:
        container: The container instance.
        user: Database user or sys.
        password: User password.
        service_name: Oracle service or PDB name.
        sql: SQL statement or script.
        as_sysdba: Whether to connect with SYSDBA administrative privileges.
        whenever_sqlerror: SQL*Plus WHENEVER SQLERROR directive.

    Returns:
        Tuple of exit code and output bytes.
    """
    script = "\n".join([
        "SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF",
        "WHENEVER OSERROR EXIT 9",
        f"WHENEVER SQLERROR {whenever_sqlerror}",
        _normalize_sqlplus_statement(sql),
        "EXIT",
        "",
    ])
    auth_suffix = " as sysdba" if as_sysdba else ""
    connect_string = f"{user}/{password}@//localhost:1521/{service_name}{auth_suffix}"
    command = f"printf '%s' {shlex.quote(script)} | sqlplus -L -S {shlex.quote(connect_string)}"
    result = container.exec_run(["bash", "-lc", command])
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)
