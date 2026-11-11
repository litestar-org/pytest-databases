"""Oracle Database and Autonomous Database Free container fixtures and wallet helpers."""

from __future__ import annotations

import contextlib
import importlib
import io
import math
import os
import re
import shlex
import tarfile
import tempfile
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import filelock
import pytest

from pytest_databases._service import ContainerService
from pytest_databases.helpers import (
    env_port,
    exec_output_to_bytes,
    get_xdist_worker_num,
    read_init_scripts,
    run_container_init_once,
    simple_string_hash,
    tcp_port_open,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "DEFAULT_ORACLE_ADB_IMAGE",
    "DEFAULT_ORACLE_ADB_PASSWORD",
    "DEFAULT_ORACLE_ADB_WALLET_PATH",
    "ORACLE_ADB_ADW_SERVICES",
    "ORACLE_ADB_AJD_SERVICES",
    "ORACLE_ADB_APEX_SERVICES",
    "ORACLE_ADB_ATP_SERVICES",
    "ORACLE_PASSWORD",
    "ORACLE_SYSTEM_PASSWORD",
    "ORACLE_USER",
    "OracleADBService",
    "OracleService",
    "enable_oracle_ords_schema",
    "ensure_oracle_adb_user",
    "ensure_oracle_user",
    "exec_oracle_sql",
    "extract_adb_wallet",
    "oracle_18c_connection",
    "oracle_18c_image",
    "oracle_18c_port",
    "oracle_18c_service",
    "oracle_18c_service_name",
    "oracle_23ai_connection",
    "oracle_23ai_image",
    "oracle_23ai_service",
    "oracle_23ai_service_name",
    "oracle_26ai_connection",
    "oracle_26ai_image",
    "oracle_26ai_port",
    "oracle_26ai_service",
    "oracle_26ai_service_name",
    "oracle_adb_admin_password",
    "oracle_adb_devices",
    "oracle_adb_filesystemio_options",
    "oracle_adb_hostname",
    "oracle_adb_image",
    "oracle_adb_password",
    "oracle_adb_port",
    "oracle_adb_service",
    "oracle_adb_startup_timeout",
    "oracle_adb_tz",
    "oracle_adb_volumes",
    "oracle_adb_wallet_dir",
    "oracle_adb_wallet_password",
    "oracle_adb_workload_type",
    "oracle_password",
    "oracle_port",
    "oracle_responsive",
    "oracle_service",
    "oracle_startup_connection",
    "oracle_startup_timeout",
    "oracle_system_password",
    "oracle_user",
    "parse_tnsnames",
    "provide_oracle_adb_service",
    "provide_oracle_service",
    "rewrite_sqlnet_ora",
    "rewrite_tnsnames",
    "xdist_oracle_isolation_level",
]

ORACLE_USER = "app"
ORACLE_PASSWORD = "super-secret"
ORACLE_SYSTEM_PASSWORD = "super-secret"
DEFAULT_ORACLE_ADB_IMAGE = "container-registry.oracle.com/database/adb-free:latest-26ai"
DEFAULT_ORACLE_ADB_PASSWORD = "Welcome12345!"
DEFAULT_ORACLE_ADB_WALLET_PATH = "/u01/app/oracle/wallets/tls_wallet"
DEFAULT_ORACLE_ADB_FILESYSTEMIO_OPTIONS = "NONE"
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
ORACLE_ADB_AJD_SERVICES: tuple[str, ...] = (
    "myajd_high",
    "myajd_medium",
    "myajd_low",
    "myajd_tp",
    "myajd_tpurgent",
)
ORACLE_ADB_APEX_SERVICES: tuple[str, ...] = (
    "myapex_high",
    "myapex_medium",
    "myapex_low",
    "myapex_tp",
    "myapex_tpurgent",
)
_FILESYSTEMIO_OPTIONS: tuple[str, ...] = ("NONE", "ASYNC", "DIRECTIO", "SETALL")
_WORKLOAD_SERVICE_MAP: dict[str, tuple[str, ...]] = {
    "ATP": ORACLE_ADB_ATP_SERVICES,
    "ADW": ORACLE_ADB_ADW_SERVICES,
    "AJD": ORACLE_ADB_AJD_SERVICES,
    "APEX": ORACLE_ADB_APEX_SERVICES,
}
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
_TRANSIENT_ORACLE_ERROR_MARKERS: tuple[str, ...] = (
    "ora-01033",
    "ora-01034",
    "ora-12514",
    "ora-12516",
    "ora-12519",
    "ora-12520",
    "ora-12528",
    "ora-00054",
    "ora-00060",
    "ora-04021",
)
_SQLPLUS_ERROR_PATTERN: re.Pattern[bytes] = re.compile(
    rb"^(?:ORA-\d{5}:|PLS-\d{5}:|SP2-\d{4}:)",
    re.MULTILINE,
)


@dataclass
class OracleService(ServiceContainer):
    """Container handle with administrative and application credentials for Oracle."""

    user: str
    password: str
    system_password: str
    service_name: str

    def exec_sql(
        self,
        sql: str,
        *,
        user: str | None = None,
        password: str | None = None,
        service_name: str | None = None,
        as_sysdba: bool = False,
        cdb_root: bool = False,
        whenever_sqlerror: str = "EXIT SQL.SQLCODE",
        retry_transient: bool = False,
    ) -> tuple[int, bytes]:
        """Execute ``sql`` via in-container ``sqlplus`` against this Oracle service.

        Args:
            sql: SQL statement or PL/SQL script to run.
            user: Optional login override (defaults to ``"sys"`` when ``as_sysdba`` is set, else ``self.user``).
            password: Optional password override (defaults to ``system_password`` for administrative execution).
            service_name: Optional TNS/PDB service override (defaults to ``self.service_name``).
            as_sysdba: Connect with ``AS SYSDBA`` administrative privileges over TNS.
            cdb_root: Connect directly to ``CDB$ROOT`` via OS authentication (``sqlplus -L -S / as sysdba``).
            whenever_sqlerror: SQL*Plus ``WHENEVER SQLERROR`` directive.
            retry_transient: Retry boundedly on transient listener/startup/catalog lock errors.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        if cdb_root:
            return exec_oracle_sql(
                self.container,
                sql,
                as_sysdba=True,
                whenever_sqlerror=whenever_sqlerror,
                retry_transient=retry_transient,
            )
        default_user = "sys" if as_sysdba else self.user
        resolved_user = default_user if user is None else user
        if password is not None:
            resolved_password = password
        elif as_sysdba or resolved_user.lower() in {"sys", "system", "admin"}:
            resolved_password = self.system_password
        else:
            resolved_password = self.password
        return exec_oracle_sql(
            self.container,
            sql,
            service_name=self.service_name if service_name is None else service_name,
            user=resolved_user,
            password=resolved_password,
            as_sysdba=as_sysdba,
            whenever_sqlerror=whenever_sqlerror,
            retry_transient=retry_transient,
        )


@dataclass
class OracleADBService(OracleService):
    """Container handle for Oracle Autonomous Database Free with TLS/mTLS wallet, ORDS, and MongoDB API support."""

    tls_port: int
    wallet_password: str
    workload_type: str
    service_names: tuple[str, ...]
    ords_port: int = 8443
    mongo_port: int = 27017
    wallet_dir: Path | None = None

    @property
    def ca_cert_path(self) -> Path | None:
        """Path to the extracted ``adb_container.cert`` CA certificate when ``wallet_dir`` is populated."""
        return self.wallet_dir / "adb_container.cert" if self.wallet_dir is not None else None

    @property
    def ords_url(self) -> str:
        """HTTPS base URL for Oracle REST Data Services (ORDS)."""
        return f"https://{self.host}:{self.ords_port}/ords/"

    @property
    def apex_url(self) -> str:
        """HTTPS URL for Oracle APEX inside the ADB-Free container."""
        return f"https://{self.host}:{self.ords_port}/ords/apex"

    @property
    def sql_developer_url(self) -> str:
        """HTTPS URL for Oracle SQL Developer Web (Database Actions)."""
        return f"https://{self.host}:{self.ords_port}/ords/sql-developer"

    @property
    def mongo_uri(self) -> str:
        """MongoDB API connection URI for the ADB-Free container on ``mongo_port``."""
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        return (
            f"mongodb://{user}:{password}@{self.host}:{self.mongo_port}/{user}"
            "?authMechanism=PLAIN&authSource=$external&ssl=true&retryWrites=false&loadBalanced=true"
        )

    def extract_wallet(self, target_dir: Path) -> Path:
        """Extract the container wallet files into ``target_dir`` and rewrite ``tnsnames.ora`` and ``sqlnet.ora``."""
        return extract_adb_wallet(
            self.container,
            target_dir,
            host=self.host,
            port=self.port,
            tls_port=self.tls_port,
        )

    def enable_ords_schema(
        self,
        schema: str | None = None,
        *,
        url_mapping_pattern: str | None = None,
        auto_rest_auth: bool = False,
    ) -> None:
        """REST-enable ``schema`` (defaults to ``self.user``) for ORDS, SQL Developer Web, and MongoDB API."""
        target_schema = schema or self.user
        enable_oracle_ords_schema(
            self.container,
            user=target_schema,
            password=self.password,
            service_name=self.service_name,
            url_mapping_pattern=url_mapping_pattern,
            auto_rest_auth=auto_rest_auth,
        )


def oracle_responsive(host: str, port: int, service_name: str, user: str, password: str) -> bool:
    """Check whether an Oracle instance responds to a ``SELECT 1 FROM dual`` query via ``oracledb``.

    .. deprecated:: 0.20.0
        ``oracle_responsive`` is deprecated in v0.20.0 and will be removed in v1.0.0.

    Returns:
        True when the query returns ``1``, otherwise False.
    """
    warnings.warn(
        "'oracle_responsive' is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Check readiness through 'oracle_service' or your own oracledb connection.",
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
    """Rewrite ``HOST``, ``PORT``, and ``SSL_SERVER_DN_MATCH`` entries in ``tnsnames.ora`` for host access.

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
    return re.sub(
        r"(\(\s*SSL_SERVER_DN_MATCH\s*=\s*)(?:YES|ON|TRUE)(\s*\))",
        r"\g<1>NO\2",
        updated,
        flags=re.IGNORECASE,
    )


def rewrite_sqlnet_ora(sqlnet_content: str, wallet_dir: Path) -> str:
    """Rewrite ``sqlnet.ora`` ``WALLET_LOCATION`` ``DIRECTORY`` to ``wallet_dir`` and disable DN matching.

    Args:
        sqlnet_content: Original ``sqlnet.ora`` content.
        wallet_dir: Host directory containing the extracted wallet files.

    Returns:
        Updated ``sqlnet.ora`` text.
    """
    resolved_dir = str(wallet_dir.resolve())
    updated = re.sub(
        r'(\(\s*DIRECTORY\s*=\s*)"?[^")]*"?(\s*\))',
        lambda m: f'{m.group(1)}"{resolved_dir}"{m.group(2)}',
        sqlnet_content,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"(SSL_SERVER_DN_MATCH\s*=\s*)(?:YES|ON|TRUE)",
        r"\g<1>NO",
        updated,
        flags=re.IGNORECASE,
    )


def extract_adb_wallet(
    container: Container,
    target_dir: Path,
    *,
    host: str,
    port: int,
    tls_port: int | None = None,
    container_wallet_path: str = DEFAULT_ORACLE_ADB_WALLET_PATH,
) -> Path:
    """Extract the TLS/mTLS wallet directory from an Oracle ADB-Free container and rewrite ``tnsnames.ora`` and ``sqlnet.ora``.

    Args:
        container: Running Oracle ADB-Free container.
        target_dir: Destination host directory where wallet files will be written.
        host: Mapped container host address.
        port: Mapped port for internal port 1521.
        tls_port: Optional mapped port for internal port 1522.
        container_wallet_path: Path to the wallet directory inside the container.

    Returns:
        Path to ``target_dir`` containing extracted wallet files (``cwallet.sso``, ``ewallet.p12``,
        ``ewallet.pem``, ``keystore.jks``, ``truststore.jks``, ``ojdbc.properties``,
        ``adb_container.cert``, ``tnsnames.ora``, ``sqlnet.ora``).
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
            lower_name = filename.lower()
            if lower_name == "tnsnames.ora":
                text = data.decode("utf-8", errors="replace")
                rewritten = rewrite_tnsnames(text, host=host, port=port, tls_port=tls_port)
                dest_file.write_text(rewritten, encoding="utf-8")
            elif lower_name == "sqlnet.ora":
                text = data.decode("utf-8", errors="replace")
                rewritten = rewrite_sqlnet_ora(text, target_dir)
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

    Existing users (``ORA-01920``) have their password synchronized (tolerating ``ORA-28007`` when password-reuse
    rules reject the current password) and unlocked before applying grants and tablespace quota. Transient Oracle
    startup, listener, or lock errors are retried via ``_run_sqlplus_with_retry``.

    Args:
        container: The container instance.
        user: Effective username to create.
        password: User password.
        service_name: Oracle service or PDB name.
        system_password: SYS administrative user password.

    Returns:
        ``True`` if the SQL*Plus provisioning command exited cleanly.
    """
    escaped_password = password.replace("'", "''")
    create_user = f'CREATE USER {user} IDENTIFIED BY "{escaped_password}"'
    reset_password = f'ALTER USER {user} IDENTIFIED BY "{escaped_password}"'
    setup_script = "\n".join([
        "BEGIN",
        f"  EXECUTE IMMEDIATE '{create_user}';",
        "EXCEPTION",
        "  WHEN OTHERS THEN",
        "    IF SQLCODE != -1920 THEN",
        "      RAISE;",
        "    END IF;",
        "    BEGIN",
        f"      EXECUTE IMMEDIATE '{reset_password}';",
        "    EXCEPTION",
        "      WHEN OTHERS THEN",
        "        IF SQLCODE != -28007 THEN",
        "          RAISE;",
        "        END IF;",
        "    END;",
        "END;",
        "/",
        f"ALTER USER {user} ACCOUNT UNLOCK;",
        f"GRANT CONNECT, RESOURCE, DBA TO {user};",
        f"ALTER USER {user} QUOTA UNLIMITED ON USERS;",
    ])
    exit_code, _ = _run_sqlplus_with_retry(
        container,
        user="sys",
        password=system_password,
        service_name=service_name,
        sql=setup_script,
        as_sysdba=True,
        whenever_sqlerror="EXIT SQL.SQLCODE",
    )
    return exit_code == 0


def ensure_oracle_adb_user(
    container: Container,
    user: str,
    password: str,
    service_name: str,
    admin_password: str,
) -> None:
    """Provision an Oracle Autonomous Database application user via the ``ADMIN`` account.

    An existing user (``ORA-01920``) gets its password reset instead of being recreated; ``ORA-28007`` from that reset
    (the ADB password profile rejects reusing the current password) is ignored because the password is already
    correct. Any other error stops the script.

    Args:
        container: Running Oracle ADB-Free container.
        user: Application username to create or update.
        password: Password meeting ``CLOUD_VERIFY_FUNCTION`` complexity rules.
        service_name: Autonomous Database service name (e.g. ``myatp_high.adb.oraclecloud.com``).
        admin_password: Password for the ``ADMIN`` administrative account.

    Raises:
        RuntimeError: If creating, unlocking, or granting privileges to the user fails.
    """
    escaped_password = password.replace("'", "''")
    create_user = (
        f'CREATE USER {user} IDENTIFIED BY "{escaped_password}" DEFAULT TABLESPACE DATA TEMPORARY TABLESPACE TEMP'
    )
    reset_password = f'ALTER USER {user} IDENTIFIED BY "{escaped_password}"'
    setup_script = "\n".join([
        "BEGIN",
        f"  EXECUTE IMMEDIATE '{create_user}';",
        "EXCEPTION",
        "  WHEN OTHERS THEN",
        "    IF SQLCODE != -1920 THEN",
        "      RAISE;",
        "    END IF;",
        "    BEGIN",
        f"      EXECUTE IMMEDIATE '{reset_password}';",
        "    EXCEPTION",
        "      WHEN OTHERS THEN",
        "        IF SQLCODE != -28007 THEN",
        "          RAISE;",
        "        END IF;",
        "    END;",
        "END;",
        "/",
        f"ALTER USER {user} DEFAULT TABLESPACE DATA TEMPORARY TABLESPACE TEMP ACCOUNT UNLOCK;",
        f"GRANT CONNECT, RESOURCE, DWROLE, UNLIMITED TABLESPACE TO {user};",
        f"ALTER USER {user} QUOTA UNLIMITED ON DATA;",
    ])
    exit_code, output = _run_sqlplus_with_retry(
        container,
        user="admin",
        password=admin_password,
        service_name=service_name,
        sql=setup_script,
        as_sysdba=False,
        whenever_sqlerror="EXIT SQL.SQLCODE",
    )
    if exit_code != 0:
        msg = f"Failed to provision Oracle ADB user {user!r} (exit {exit_code}): {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)


def enable_oracle_ords_schema(
    container: Container,
    user: str,
    password: str,
    service_name: str,
    *,
    url_mapping_pattern: str | None = None,
    auto_rest_auth: bool = False,
) -> None:
    """REST-enable an Oracle Autonomous Database schema for ORDS, SQL Developer Web, and MongoDB API.

    Args:
        container: Running Oracle ADB-Free container.
        user: Database schema owner username.
        password: User password.
        service_name: Autonomous Database service name.
        url_mapping_pattern: Optional URL mapping slug (defaults to ``user.lower()``).
        auto_rest_auth: Whether to require authentication on auto-REST metadata endpoints.

    Raises:
        RuntimeError: If ``ORDS.ENABLE_SCHEMA`` fails.
    """
    schema_upper = user.upper()
    escaped_schema = schema_upper.replace("'", "''")
    escaped_pattern = (url_mapping_pattern or user).lower().replace("'", "''")
    auth_literal = "TRUE" if auto_rest_auth else "FALSE"
    plsql = (
        "BEGIN "
        "ORDS.ENABLE_SCHEMA("
        "p_enabled => TRUE, "
        f"p_schema => '{escaped_schema}', "
        "p_url_mapping_type => 'BASE_PATH', "
        f"p_url_mapping_pattern => '{escaped_pattern}', "
        f"p_auto_rest_auth => {auth_literal}"
        "); "
        "COMMIT; "
        "END;\n/"
    )
    exit_code, output = _run_sqlplus_with_retry(
        container,
        user=user,
        password=password,
        service_name=service_name,
        sql=plsql,
        as_sysdba=False,
        whenever_sqlerror="EXIT SQL.SQLCODE",
    )
    if exit_code != 0:
        msg = f"Failed to REST-enable schema {schema_upper!r} (exit {exit_code}): {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)


def exec_oracle_sql(
    container: Container,
    sql: str,
    *,
    service_name: str | None = None,
    user: str | None = None,
    password: str | None = None,
    as_sysdba: bool = False,
    whenever_sqlerror: str = "EXIT SQL.SQLCODE",
    retry_transient: bool = False,
) -> tuple[int, bytes]:
    """Execute SQL or PL/SQL inside a running Oracle container via ``sqlplus``.

    Supports both TNS service/PDB execution (``user/password@//localhost:1521/service``) and
    OS-authenticated ``CDB$ROOT`` execution (``sqlplus -L -S / as sysdba`` when ``as_sysdba=True``
    and ``service_name``, ``user``, and ``password`` are omitted). Modulo-256 zero exit codes on
    ``ORA-``/``PLS-``/``SP2-`` errors are normalized to ``1`` unless ``whenever_sqlerror="CONTINUE"``.

    Args:
        container: Running Oracle container handle.
        sql: SQL statement or PL/SQL block.
        service_name: Target PDB or service name (omit with ``as_sysdba=True`` for ``CDB$ROOT``).
        user: Database username (omit with ``as_sysdba=True`` for OS authentication).
        password: User password.
        as_sysdba: Connect with ``AS SYSDBA`` administrative privileges.
        whenever_sqlerror: SQL*Plus ``WHENEVER SQLERROR`` directive.
        retry_transient: Retry boundedly on transient listener, startup, or catalog lock errors.

    Returns:
        Tuple of ``(exit_code, output_bytes)``.

    Raises:
        ValueError: If TNS execution is missing ``service_name``, ``user``, or ``password``.
    """
    if service_name is None and user is None and password is None and as_sysdba:
        return _exec_sqlplus_os_sysdba(
            container,
            sql,
            whenever_sqlerror=whenever_sqlerror,
            retry_transient=retry_transient,
        )
    if not service_name or not user or password is None:
        msg = (
            "exec_oracle_sql requires 'service_name', 'user', and 'password' unless executing against "
            "CDB$ROOT via as_sysdba=True with all three omitted."
        )
        raise ValueError(msg)
    if retry_transient:
        return _run_sqlplus_with_retry(
            container,
            user=user,
            password=password,
            service_name=service_name,
            sql=sql,
            as_sysdba=as_sysdba,
            whenever_sqlerror=whenever_sqlerror,
        )
    return _exec_sqlplus(
        container,
        user=user,
        password=password,
        service_name=service_name,
        sql=sql,
        as_sysdba=as_sysdba,
        whenever_sqlerror=whenever_sqlerror,
    )


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
    *,
    host_port: int | None = None,
    env: Mapping[str, str] | None = None,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    shm_size: int | str | None = None,
    mem_limit: str | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
    timeout: int = 180,
    pause: float = 1.0,
) -> Generator[OracleService, None, None]:
    """Start and manage an Oracle database container with consistent privilege provisioning.

    Both single-process and ``pytest-xdist`` runs run :func:`ensure_oracle_user` against
    ``effective_user`` so ``APP_USER`` always receives identical ``CONNECT``, ``RESOURCE``,
    ``DBA``, and ``QUOTA UNLIMITED ON USERS`` privileges regardless of concurrency mode.

    Args:
        docker_service: The container service manager.
        image: Container image for Oracle.
        name: Logical container service name.
        service_name: Oracle PDB or service name.
        user: Default application username.
        password: Application user password.
        system_password: Administrative SYS password.
        isolation_level: xdist isolation strategy (database or server).
        host_port: Optional pinned host TCP port for listener port 1521.
        env: Optional extra container environment variables merged over defaults.
        volumes: Optional container volume mounts.
        shm_size: Optional ``/dev/shm`` size (important for larger Oracle SGA configurations).
        mem_limit: Optional container memory limit (for example ``"4g"``).
        init_sql: Optional SQL/PLSQL statement, file path, or sequence executed once per target user/PDB.
        timeout: Maximum startup wait time in seconds.
        pause: Sleep interval in seconds between readiness polling attempts.

    Yields:
        An OracleService handle configured for the active worker.

    Raises:
        ValueError: If ``timeout`` is not a positive integer or ``pause`` is not a positive finite number.
    """
    _validate_positive_timeout(timeout, name="timeout")
    pause = _validate_positive_pause(pause, name="pause")
    worker_num, resolved_name, effective_user = _resolve_oracle_targets(name, user, isolation_level)
    user_provisioned = False

    def check(_service: ServiceContainer) -> bool:
        nonlocal user_provisioned
        if not tcp_port_open(_service.host, _service.port):
            return False
        if not user_provisioned:
            if not _provision_oracle_app_user(
                _service.container,
                user=effective_user,
                password=password,
                service_name=service_name,
                system_password=system_password,
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
        name=resolved_name,
        check=check,
        container_port=1521,
        host_port=host_port,
        timeout=timeout,
        pause=pause,
        transient=worker_num is not None and isolation_level == "server",
        volumes=volumes,
        shm_size=shm_size,
        mem_limit=mem_limit,
        env=_build_oracle_env(user=user, password=password, system_password=system_password, extra_env=env),
    ) as service:
        _apply_oracle_init_sql(
            service.container,
            service_name=service_name,
            user=effective_user,
            password=password,
            init_sql=init_sql,
        )
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
    *,
    tz: str = "UTC",
    host_port: int | None = None,
    env: Mapping[str, str] | None = None,
    wallet_dir: Path | None = None,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    devices: list[str] | None = None,
    shm_size: int | str | None = None,
    mem_limit: str | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
    filesystemio_options: str | None = DEFAULT_ORACLE_ADB_FILESYSTEMIO_OPTIONS,
    timeout: int = 420,
    pause: float = 2.0,
) -> Generator[OracleADBService, None, None]:
    """Start and manage an Oracle Autonomous AI Database Free (26ai) container.

    The image's server parameter file sets ``filesystemio_options`` to direct I/O, which cannot open the control
    files when the container storage has 4096-byte logical sectors (``ORA-27072``, ``ORA-00202``, then
    ``ORA-01034``). By default the container command therefore rewrites the server parameter file with
    ``filesystemio_options='NONE'`` (``CREATE PFILE FROM SPFILE`` and ``CREATE SPFILE FROM PFILE`` against the idle
    instance) and then runs the image entrypoint. Pass ``filesystemio_options=None`` to start the image unchanged.

    Args:
        docker_service: The container service manager.
        image: Oracle ADB-Free container image.
        name: Logical container service name.
        workload_type: Autonomous workload profile (``ATP``, ``ADW``, ``AJD``, or ``APEX``).
        hostname: Container hostname required by ADB-Free initialization scripts.
        user: Default application username.
        password: Application user password meeting ``CLOUD_VERIFY_FUNCTION`` rules.
        system_password: ``ADMIN`` account password.
        wallet_password: Password protecting the container's TLS/mTLS wallet.
        isolation_level: xdist isolation strategy (database or server).
        tz: Database timezone passed via ``MY_TZ`` (defaults to ``UTC``).
        host_port: Optional pinned host TCP port for listener port 1521.
        env: Optional extra container environment variables merged over defaults.
        wallet_dir: Optional host directory where the container wallet will be extracted automatically.
        volumes: Optional container volume mounts (e.g. for ``/u01/app/oracle/wallets/tls_wallet``).
        devices: Optional device mappings for the container runtime host (for example ``["/dev/fuse"]``).
        shm_size: Optional ``/dev/shm`` size forwarded to container creation.
        mem_limit: Optional container memory limit forwarded to container creation.
        init_sql: Optional SQL/PLSQL statement, file path, or sequence executed once per target user/service.
        filesystemio_options: ``filesystemio_options`` value written to the server parameter file before the
            database starts (``NONE``, ``ASYNC``, ``DIRECTIO``, or ``SETALL``), or ``None`` for the image default.
        timeout: Maximum startup wait time in seconds.
        pause: Sleep interval in seconds between readiness polling attempts.

    Yields:
        An OracleADBService handle configured for the active worker.

    Raises:
        ValueError: If ``workload_type`` is not ``ATP``, ``ADW``, ``AJD``, or ``APEX``, ``filesystemio_options``
            is not a valid ``filesystemio_options`` value, ``timeout`` is not a positive integer, or ``pause`` is
            not a positive finite number.
    """
    _validate_positive_timeout(timeout, name="timeout")
    pause = _validate_positive_pause(pause, name="pause")
    normalized_workload = workload_type.strip().upper()
    if normalized_workload not in _WORKLOAD_SERVICE_MAP:
        msg = f"Unknown Oracle ADB workload type {workload_type!r}; expected one of {', '.join(_WORKLOAD_SERVICE_MAP)}"
        raise ValueError(msg)
    entrypoint: list[str] | None = None
    command: list[str] | None = None
    if filesystemio_options is not None:
        entrypoint = ["/bin/bash", "-c"]
        command = [_adb_filesystemio_command(filesystemio_options)]
    service_names = _WORKLOAD_SERVICE_MAP[normalized_workload]
    default_service_name = f"{service_names[0]}.adb.oraclecloud.com"

    worker_num, resolved_name, effective_user = _resolve_oracle_targets(name, user, isolation_level)
    user_provisioned = False

    def check(_service: ServiceContainer) -> bool:
        nonlocal user_provisioned
        if not tcp_port_open(_service.host, _service.port):
            return False
        if not user_provisioned:
            if not _provision_oracle_adb_app_user(
                _service.container,
                user=effective_user,
                password=password,
                service_name=default_service_name,
                admin_password=system_password,
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

    with docker_service.run(
        image=image,
        name=resolved_name,
        check=check,
        container_port=1521,
        host_port=host_port,
        extra_ports={1522: None, 8443: None, 27017: None},
        timeout=timeout,
        pause=pause,
        transient=worker_num is not None and isolation_level == "server",
        hostname=hostname,
        cap_add=["SYS_ADMIN"],
        devices=devices,
        volumes=volumes,
        shm_size=shm_size,
        mem_limit=mem_limit,
        entrypoint=entrypoint,
        command=command,
        env=_build_oracle_adb_env(
            workload=normalized_workload,
            wallet_password=wallet_password,
            admin_password=system_password,
            tz=tz,
            extra_env=env,
        ),
    ) as service:
        _apply_oracle_init_sql(
            service.container,
            service_name=default_service_name,
            user=effective_user,
            password=password,
            init_sql=init_sql,
        )
        tls_port, ords_port, mongo_port, extracted_wallet_dir = _resolve_adb_endpoints(service, wallet_dir)
        yield OracleADBService(
            host=service.host,
            port=service.port,
            tls_port=tls_port,
            ords_port=ords_port,
            mongo_port=mongo_port,
            wallet_dir=extracted_wallet_dir,
            container=service.container,
            system_password=system_password,
            user=effective_user,
            password=password,
            service_name=default_service_name,
            wallet_password=wallet_password,
            workload_type=normalized_workload,
            service_names=service_names,
        )


@pytest.fixture(scope="session")
def xdist_oracle_isolation_level() -> XdistIsolationLevel:
    """Determine Oracle xdist isolation mode (database or server)."""
    return "database"


@pytest.fixture(autouse=False, scope="session")
def oracle_26ai_image(request: pytest.FixtureRequest) -> str:
    """Container image for Oracle AI Database 26ai Free (``23.26.x`` track on ``gvenzl/oracle-free``)."""
    default = os.getenv("ORACLE_26AI_IMAGE", "gvenzl/oracle-free:23-slim-faststart")
    return str(_resolve_legacy_oracle_23ai_override(request, "oracle_23ai_image", "oracle_26ai_image", default))


@pytest.fixture(autouse=False, scope="session")
def oracle_26ai_service_name(request: pytest.FixtureRequest) -> str:
    """Default PDB service name for Oracle AI Database 26ai Free."""
    default = os.getenv("ORACLE_26AI_SERVICE_NAME", "FREEPDB1")
    return str(
        _resolve_legacy_oracle_23ai_override(
            request,
            "oracle_23ai_service_name",
            "oracle_26ai_service_name",
            default,
        )
    )


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_image() -> str:
    """Deprecated alias for ``oracle_26ai_image`` preserved for v0.19.0 callers.

    .. deprecated:: 0.20.0
        Use ``oracle_26ai_image`` instead. ``oracle_23ai_image`` will be removed in v1.0.0.
    """
    warnings.warn(
        "The 'oracle_23ai_image' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'oracle_26ai_image' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return os.getenv("ORACLE_26AI_IMAGE", "gvenzl/oracle-free:23-slim-faststart")


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service_name() -> str:
    """Deprecated alias for ``oracle_26ai_service_name`` preserved for v0.19.0 callers.

    .. deprecated:: 0.20.0
        Use ``oracle_26ai_service_name`` instead. ``oracle_23ai_service_name`` will be removed in v1.0.0.
    """
    warnings.warn(
        "The 'oracle_23ai_service_name' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'oracle_26ai_service_name' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return os.getenv("ORACLE_26AI_SERVICE_NAME", "FREEPDB1")


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_image() -> str:
    """Container image for Oracle Database 18c XE."""
    return "gvenzl/oracle-xe:18-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service_name() -> str:
    """Default PDB service name for Oracle Database 18c XE."""
    return "xepdb1"


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_image() -> str:
    """Container image for Oracle Autonomous AI Database Free (26ai)."""
    return os.getenv("ORACLE_ADB_IMAGE", DEFAULT_ORACLE_ADB_IMAGE)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_workload_type() -> str:
    """Workload type for Oracle Autonomous Database Free (``ATP``, ``ADW``, ``AJD``, or ``APEX``)."""
    return os.getenv("ORACLE_ADB_WORKLOAD_TYPE", "ATP")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_hostname() -> str:
    """Container hostname for Oracle Autonomous Database Free."""
    return os.getenv("ORACLE_ADB_HOSTNAME", "adb-free.local")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_tz() -> str:
    """Database timezone (``MY_TZ``) for Oracle Autonomous Database Free."""
    return os.getenv("ORACLE_ADB_TZ", "UTC")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_wallet_password() -> str:
    """Wallet password for Oracle Autonomous Database Free (meets ``CLOUD_VERIFY_FUNCTION`` rules)."""
    return os.getenv("ORACLE_ADB_WALLET_PASSWORD", DEFAULT_ORACLE_ADB_PASSWORD)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_password() -> str:
    """Application password for Oracle Autonomous Database Free (meets ``CLOUD_VERIFY_FUNCTION`` rules)."""
    return os.getenv("ORACLE_ADB_PASSWORD", DEFAULT_ORACLE_ADB_PASSWORD)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_admin_password() -> str:
    """Administrative ``ADMIN`` password for Oracle Autonomous Database Free."""
    return os.getenv("ORACLE_ADB_ADMIN_PASSWORD", DEFAULT_ORACLE_ADB_PASSWORD)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_wallet_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Host directory where the Oracle Autonomous Database Free wallet is extracted."""
    return tmp_path_factory.mktemp("oracle_adb_wallet")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_volumes() -> dict[str, dict[str, str]] | list[str] | None:
    """Optional volume mounts for Oracle Autonomous Database Free."""
    return None


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_filesystemio_options() -> str | None:
    """``filesystemio_options`` written to the ADB-Free server parameter file before the database starts.

    Defaults to ``NONE`` (env ``ORACLE_ADB_FILESYSTEMIO_OPTIONS``) so the instance opens on storage with
    4096-byte logical sectors. Override this fixture to return ``None`` to keep the image's own setting.
    """
    return os.getenv("ORACLE_ADB_FILESYSTEMIO_OPTIONS", DEFAULT_ORACLE_ADB_FILESYSTEMIO_OPTIONS)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_devices() -> list[str] | None:
    """Optional device mappings for Oracle Autonomous Database Free, such as ``["/dev/fuse"]``.

    The devices must exist on the container runtime host, which is not necessarily the host running pytest.
    """
    return None


@pytest.fixture(autouse=False, scope="session")
def oracle_user() -> str:
    """Default application username for Oracle."""
    return os.getenv("ORACLE_USER", ORACLE_USER)


@pytest.fixture(autouse=False, scope="session")
def oracle_password() -> str:
    """Default application password for Oracle."""
    return os.getenv("ORACLE_PASSWORD", ORACLE_PASSWORD)


@pytest.fixture(autouse=False, scope="session")
def oracle_system_password() -> str:
    """Default administrative SYS password for Oracle."""
    return os.getenv("ORACLE_SYSTEM_PASSWORD", ORACLE_SYSTEM_PASSWORD)


@pytest.fixture(autouse=False, scope="session")
def oracle_port() -> int | None:
    """Optional pinned host port for the default Oracle container (``ORACLE_PORT``)."""
    return env_port("ORACLE_PORT")


@pytest.fixture(autouse=False, scope="session")
def oracle_26ai_port(oracle_port: int | None) -> int | None:
    """Optional pinned host port for Oracle AI Database 26ai Free (``ORACLE_26AI_PORT`` or ``ORACLE_PORT``)."""
    pinned = env_port("ORACLE_26AI_PORT")
    return oracle_port if pinned is None else pinned


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_port() -> int | None:
    """Optional pinned host port for Oracle 18c XE (``ORACLE_18C_PORT``)."""
    return env_port("ORACLE_18C_PORT")


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_port() -> int | None:
    """Optional pinned host port for Oracle ADB-Free (``ORACLE_ADB_PORT``)."""
    return env_port("ORACLE_ADB_PORT")


@pytest.fixture(autouse=False, scope="session")
def oracle_startup_timeout() -> int:
    """Startup timeout in seconds for Oracle Database 18c and 26ai containers."""
    return _parse_timeout("ORACLE_STARTUP_TIMEOUT", 180)


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_startup_timeout() -> int:
    """Startup timeout in seconds for Oracle Autonomous AI Database Free containers."""
    return _parse_timeout("ORACLE_ADB_STARTUP_TIMEOUT", 420)


@pytest.fixture(autouse=False, scope="session")
def oracle_26ai_service(
    docker_service: DockerService,
    xdist_oracle_isolation_level: XdistIsolationLevel,
    oracle_26ai_image: str,
    oracle_26ai_service_name: str,
    oracle_user: str,
    oracle_password: str,
    oracle_system_password: str,
    oracle_startup_timeout: int,
    oracle_26ai_port: int | None,
) -> Generator[OracleService, None, None]:
    """Session fixture providing an Oracle AI Database 26ai Free container service.

    Yields:
        An OracleService handle.
    """
    with provide_oracle_service(
        image=oracle_26ai_image,
        name="oracle26ai",
        service_name=oracle_26ai_service_name,
        user=oracle_user,
        password=oracle_password,
        system_password=oracle_system_password,
        docker_service=docker_service,
        isolation_level=xdist_oracle_isolation_level,
        host_port=oracle_26ai_port,
        timeout=oracle_startup_timeout,
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
    oracle_startup_timeout: int,
    oracle_18c_port: int | None,
) -> Generator[OracleService, None, None]:
    """Session fixture providing an Oracle Database 18c XE container service.

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
        host_port=oracle_18c_port,
        timeout=oracle_startup_timeout,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_adb_service(
    docker_service: DockerService,
    xdist_oracle_isolation_level: XdistIsolationLevel,
    oracle_adb_image: str,
    oracle_adb_workload_type: str,
    oracle_adb_hostname: str,
    oracle_adb_tz: str,
    oracle_user: str,
    oracle_adb_password: str,
    oracle_adb_admin_password: str,
    oracle_adb_wallet_password: str,
    oracle_adb_wallet_dir: Path,
    oracle_adb_volumes: dict[str, dict[str, str]] | list[str] | None,
    oracle_adb_devices: list[str] | None,
    oracle_adb_filesystemio_options: str | None,
    oracle_adb_startup_timeout: int,
    oracle_adb_port: int | None,
) -> Generator[OracleADBService, None, None]:
    """Session fixture providing an Oracle Autonomous AI Database Free (26ai) container service.

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
        password=oracle_adb_password,
        system_password=oracle_adb_admin_password,
        wallet_password=oracle_adb_wallet_password,
        isolation_level=xdist_oracle_isolation_level,
        tz=oracle_adb_tz,
        host_port=oracle_adb_port,
        wallet_dir=oracle_adb_wallet_dir,
        volumes=oracle_adb_volumes,
        devices=oracle_adb_devices,
        filesystemio_options=oracle_adb_filesystemio_options,
        timeout=oracle_adb_startup_timeout,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service(oracle_26ai_service: OracleService) -> OracleService:
    """Deprecated alias for ``oracle_26ai_service`` preserved for v0.19.0 callers.

    .. deprecated:: 0.20.0
        Use ``oracle_26ai_service`` or ``oracle_service`` instead. ``oracle_23ai_service`` will be removed in v1.0.0.
    """
    warnings.warn(
        "The 'oracle_23ai_service' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'oracle_26ai_service' or 'oracle_service' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return oracle_26ai_service


@pytest.fixture(autouse=False, scope="session")
def oracle_service(request: pytest.FixtureRequest) -> OracleService:
    """Alias for the latest default Oracle service (26ai)."""
    return _resolve_legacy_oracle_23ai_service(request)


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_connection(oracle_18c_service: OracleService) -> Generator[Any, None, None]:
    """Deprecated ``oracledb`` connection fixture for Oracle 18c XE.

    Yields:
        An open ``oracledb.Connection``.
    """
    with _open_oracle_connection(oracle_18c_service, "oracle_18c_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_connection(request: pytest.FixtureRequest) -> Generator[Any, None, None]:
    """Deprecated ``oracledb`` connection fixture preserved for v0.19.0 callers.

    .. deprecated:: 0.20.0
        Create an ``oracledb`` connection from ``oracle_service`` or ``oracle_26ai_service`` instead.
        ``oracle_23ai_connection`` will be removed in v1.0.0.

    Yields:
        An open ``oracledb.Connection``.
    """
    service = _resolve_legacy_oracle_23ai_service(request)
    with _open_oracle_connection(service, "oracle_23ai_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def oracle_26ai_connection(oracle_26ai_service: OracleService) -> Generator[Any, None, None]:
    """Deprecated ``oracledb`` connection fixture for Oracle AI Database 26ai Free.

    Yields:
        An open ``oracledb.Connection``.
    """
    with _open_oracle_connection(oracle_26ai_service, "oracle_26ai_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def oracle_startup_connection(oracle_26ai_service: OracleService) -> Generator[Any, None, None]:
    """Deprecated alias for ``oracle_26ai_connection`` preserved for v0.19.0 callers.

    Yields:
        An open ``oracledb.Connection``.
    """
    with _open_oracle_connection(oracle_26ai_service, "oracle_startup_connection") as conn:
        yield conn


def _has_external_fixture_override(request: pytest.FixtureRequest, name: str) -> bool:
    """Return whether ``name`` is overridden by a fixture defined outside ``pytest_databases``."""
    fixturedefs = request._fixturemanager.getfixturedefs(name, request._pyfuncitem)
    return bool(fixturedefs and not fixturedefs[-1].func.__module__.startswith("pytest_databases."))


def _resolve_legacy_oracle_23ai_override(
    request: pytest.FixtureRequest,
    legacy_name: str,
    replacement: str,
    default: Any,
) -> Any:
    """Return an external override of a deprecated ``oracle_23ai_*`` fixture, or ``default``."""
    if not _has_external_fixture_override(request, legacy_name):
        return default
    warnings.warn(
        f"Overriding the '{legacy_name}' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        f"Override '{replacement}' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return request.getfixturevalue(legacy_name)


def _resolve_legacy_oracle_23ai_service(request: pytest.FixtureRequest) -> OracleService:
    """Return a user override of ``oracle_23ai_service`` when present, otherwise ``oracle_26ai_service``."""
    if _has_external_fixture_override(request, "oracle_23ai_service"):
        warnings.warn(
            "Overriding the 'oracle_23ai_service' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
            "Override 'oracle_26ai_service' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        legacy_service: OracleService = request.getfixturevalue("oracle_23ai_service")
        return legacy_service
    service: OracleService = request.getfixturevalue("oracle_26ai_service")
    return service


@contextlib.contextmanager
def _open_oracle_connection(service: OracleService, fixture_name: str) -> Generator[Any, None, None]:
    """Open and yield a deprecated ``oracledb`` connection for ``service``.

    Yields:
        An open ``oracledb.Connection``.
    """
    warnings.warn(
        f"The '{fixture_name}' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Create an oracledb connection from 'oracle_service' instead.",
        DeprecationWarning,
        stacklevel=3,
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
        msg = "Oracle connection fixtures require the 'oracledb' package (`pip install oracledb`)."
        raise pytest.UsageError(msg) from exc


def _normalize_sqlplus_statement(sql: str) -> str:
    """Ensure a SQL statement or PL/SQL block terminates with ``;`` or ``/`` for SQL*Plus.

    Args:
        sql: The input SQL string.

    Returns:
        Terminated SQL*Plus statement.
    """
    statement = sql.strip()
    if not statement.endswith((";", "/")):
        statement = f"{statement};"
    return statement


def _adb_filesystemio_command(filesystemio_options: str) -> str:
    """Build the ADB-Free container command that sets ``filesystemio_options`` before the image entrypoint runs.

    The server parameter file is round-tripped through a text parameter file against the idle instance, so Oracle
    writes a valid binary file; the image entrypoint then starts the database with the new value.

    Args:
        filesystemio_options: One of ``NONE``, ``ASYNC``, ``DIRECTIO``, or ``SETALL`` (case-insensitive).

    Returns:
        A ``bash -c`` script that rewrites the server parameter file and then execs the image entrypoint.

    Raises:
        ValueError: If ``filesystemio_options`` is not a valid value.
    """
    value = filesystemio_options.strip().upper()
    if value not in _FILESYSTEMIO_OPTIONS:
        msg = (
            f"Invalid filesystemio_options {filesystemio_options!r}; expected one of {', '.join(_FILESYSTEMIO_OPTIONS)}"
        )
        raise ValueError(msg)
    pfile = "$HOME/pytest-databases-init.ora"
    return (
        "set -e\n"
        "sqlplus -S -L / as sysdba <<EOF\n"
        "WHENEVER SQLERROR EXIT FAILURE\n"
        f"CREATE PFILE='{pfile}' FROM SPFILE;\n"
        "EXIT\n"
        "EOF\n"
        f"sed -i '/^\\*\\.filesystemio_options=/d' \"{pfile}\"\n"
        f'echo "*.filesystemio_options=\'{value}\'" >> "{pfile}"\n'
        "sqlplus -S -L / as sysdba <<EOF\n"
        "WHENEVER SQLERROR EXIT FAILURE\n"
        f"CREATE SPFILE FROM PFILE='{pfile}';\n"
        "EXIT\n"
        "EOF\n"
        'exec "${RUNTIME_SCRIPTS:-/u01/scripts}/${ENTRYPOINT_SCRIPT:-entrypoint.sh}"\n'
    )


def _resolve_oracle_targets(
    name: str,
    user: str,
    isolation_level: XdistIsolationLevel,
) -> tuple[int | None, str, str]:
    """Resolve ``(worker_num, container_name, effective_user)`` for Oracle services."""
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return None, name, user
    if isolation_level == "server":
        return worker_num, f"{name}_{worker_num}", user
    return worker_num, name, f"{user}_{worker_num}"


def _oracle_user_lock(
    container: Container, *, service_name: str, user: str
) -> contextlib.AbstractContextManager[object]:
    """Return a cross-process file lock serializing Oracle user provisioning per container/PDB/user."""
    container_id = getattr(container, "id", None)
    if not isinstance(container_id, str) or not container_id:
        return contextlib.nullcontext()
    digest = simple_string_hash(f"{service_name}:{user.lower()}")[:12]
    lock_path = Path(tempfile.gettempdir()) / f"pytest-databases-oracle-user-{container_id[:12]}-{digest}.lock"
    return filelock.FileLock(str(lock_path), timeout=180.0)


def _provision_oracle_app_user(
    container: Container,
    *,
    user: str,
    password: str,
    service_name: str,
    system_password: str,
) -> bool:
    """Ensure ``user`` exists with ``CONNECT, RESOURCE, DBA`` and unlimited ``USERS`` quota."""
    sys_exit, sys_out = _exec_sqlplus(
        container,
        user="sys",
        password=system_password,
        service_name=service_name,
        sql="SELECT 1 FROM dual",
        as_sysdba=True,
    )
    if sys_exit != 0 or sys_out.strip() != b"1":
        return False
    with _oracle_user_lock(container, service_name=service_name, user=user):
        return ensure_oracle_user(
            container,
            user=user,
            password=password,
            service_name=service_name,
            system_password=system_password,
        )


def _provision_oracle_adb_app_user(
    container: Container,
    *,
    user: str,
    password: str,
    service_name: str,
    admin_password: str,
) -> bool:
    """Ensure ``user`` exists and is ORDS-enabled inside an Oracle ADB-Free container."""
    admin_exit, admin_out = _exec_sqlplus(
        container,
        user="admin",
        password=admin_password,
        service_name=service_name,
        sql="SELECT 1 FROM dual",
        as_sysdba=False,
    )
    if admin_exit != 0 or admin_out.strip() != b"1":
        return False
    with _oracle_user_lock(container, service_name=service_name, user=user):
        ensure_oracle_adb_user(
            container,
            user=user,
            password=password,
            service_name=service_name,
            admin_password=admin_password,
        )
        enable_oracle_ords_schema(
            container,
            user=user,
            password=password,
            service_name=service_name,
        )
    return True


def _build_oracle_env(
    *,
    user: str,
    password: str,
    system_password: str,
    extra_env: Mapping[str, str] | None,
) -> dict[str, str]:
    """Compose container environment variables for Oracle Database 18c and 26ai images."""
    container_env: dict[str, str] = {
        "ORACLE_PASSWORD": system_password,
        "APP_USER_PASSWORD": password,
        "APP_USER": user,
    }
    if extra_env:
        container_env.update(extra_env)
    return container_env


def _build_oracle_adb_env(
    *,
    workload: str,
    wallet_password: str,
    admin_password: str,
    tz: str,
    extra_env: Mapping[str, str] | None,
) -> dict[str, str]:
    """Compose container environment variables for Oracle Autonomous Database Free images."""
    container_env: dict[str, str] = {
        "WORKLOAD_TYPE": workload,
        "WALLET_PASSWORD": wallet_password,
        "ADMIN_PASSWORD": admin_password,
        "MY_TZ": tz,
    }
    if extra_env:
        container_env.update(extra_env)
    return container_env


def _resolve_adb_endpoints(
    service: ServiceContainer,
    wallet_dir: Path | None,
) -> tuple[int, int, int, Path | None]:
    """Resolve mapped TLS/ORDS/Mongo ports and optionally extract the ADB wallet."""
    tls_port = ContainerService.resolve_port(service.container, 1522)
    ords_port = ContainerService.resolve_port(service.container, 8443)
    mongo_port = ContainerService.resolve_port(service.container, 27017)
    extracted: Path | None = None
    if wallet_dir is not None:
        extracted = extract_adb_wallet(
            service.container,
            wallet_dir,
            host=service.host,
            port=service.port,
            tls_port=tls_port,
        )
    return tls_port, ords_port, mongo_port, extracted


def _apply_oracle_init_sql(
    container: Container,
    *,
    service_name: str,
    user: str,
    password: str,
    init_sql: str | Path | Sequence[str | Path] | None,
) -> None:
    """Execute ``init_sql`` scripts once per ``(container, service_name, user)``."""
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = simple_string_hash("\n/\n".join(statements))

    def _run() -> None:
        for statement in statements:
            code, output = exec_oracle_sql(
                container,
                statement,
                service_name=service_name,
                user=user,
                password=password,
                retry_transient=True,
            )
            if code != 0:
                detail = output.decode(errors="replace").strip()
                msg = f"Oracle init_sql failed for {user!r} on {service_name!r} (exit {code}): {detail}"
                raise RuntimeError(msg)

    run_container_init_once(container, f"oracle:{service_name}:{user.lower()}", fingerprint, _run)


def _exec_sqlplus_os_sysdba(
    container: Container,
    sql: str,
    *,
    whenever_sqlerror: str = "EXIT SQL.SQLCODE",
    retry_transient: bool = False,
) -> tuple[int, bytes]:
    """Execute SQL*Plus against ``CDB$ROOT`` via OS authentication (``sqlplus -L -S / as sysdba``)."""
    attempts = 5 if retry_transient else 1
    script = "\n".join([
        "SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF",
        "WHENEVER OSERROR EXIT 9",
        f"WHENEVER SQLERROR {whenever_sqlerror}",
        _normalize_sqlplus_statement(sql),
        "EXIT",
        "",
    ])
    command = f"printf '%s' {shlex.quote(script)} | sqlplus -L -S / as sysdba"
    exit_code = -1
    output = b""
    for attempt in range(attempts):
        result = container.exec_run(["bash", "-lc", command])
        exit_code = result.exit_code if result.exit_code is not None else -1
        output = exec_output_to_bytes(result.output)
        if exit_code == 0 and whenever_sqlerror.strip().upper() != "CONTINUE" and _SQLPLUS_ERROR_PATTERN.search(output):
            exit_code = 1
        if exit_code == 0 or not _is_transient_oracle_error(output):
            return exit_code, output
        if attempt < attempts - 1:
            time.sleep(0.5 * (attempt + 1))
    return exit_code, output


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
    exit_code = result.exit_code if result.exit_code is not None else -1
    output = exec_output_to_bytes(result.output)
    if exit_code == 0 and whenever_sqlerror.strip().upper() != "CONTINUE" and _SQLPLUS_ERROR_PATTERN.search(output):
        exit_code = 1
    return exit_code, output


def _is_transient_oracle_error(output: bytes) -> bool:
    """Return whether ``output`` contains a transient Oracle startup, listener, or catalog lock error."""
    decoded = output.decode(errors="replace").lower()
    return any(marker in decoded for marker in _TRANSIENT_ORACLE_ERROR_MARKERS)


def _run_sqlplus_with_retry(
    container: Container,
    *,
    user: str,
    password: str,
    service_name: str,
    sql: str,
    as_sysdba: bool = False,
    whenever_sqlerror: str = "EXIT SQL.SQLCODE",
    attempts: int = 5,
) -> tuple[int, bytes]:
    """Execute SQL*Plus inside ``container`` with bounded retries on transient Oracle errors.

    Args:
        container: The container instance.
        user: Database user or ``sys``.
        password: User password.
        service_name: Oracle service or PDB name.
        sql: SQL statement or script.
        as_sysdba: Whether to connect with SYSDBA administrative privileges.
        whenever_sqlerror: SQL*Plus ``WHENEVER SQLERROR`` directive.
        attempts: Maximum number of attempts before returning the final result.

    Returns:
        Tuple of exit code and output bytes.

    Raises:
        ValueError: If ``attempts`` is less than ``1``.
    """
    if attempts < 1:
        msg = f"attempts must be >= 1, got {attempts!r}"
        raise ValueError(msg)
    exit_code = -1
    output = b""
    for attempt in range(attempts):
        exit_code, output = _exec_sqlplus(
            container,
            user=user,
            password=password,
            service_name=service_name,
            sql=sql,
            as_sysdba=as_sysdba,
            whenever_sqlerror=whenever_sqlerror,
        )
        if exit_code == 0 or not _is_transient_oracle_error(output):
            return exit_code, output
        if attempt < attempts - 1:
            time.sleep(0.5 * (attempt + 1))
    return exit_code, output


def _validate_positive_timeout(value: int, *, name: str) -> int:
    """Validate that a timeout configuration value is a positive integer.

    Args:
        value: Candidate timeout value in seconds.
        name: Parameter or environment variable name used in error messages.

    Returns:
        The validated positive integer timeout.

    Raises:
        ValueError: If ``value`` is a boolean, not an ``int``, or less than or equal to zero.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        msg = f"{name} must be a positive integer, got {value!r}"
        raise ValueError(msg)
    return value


def _validate_positive_pause(value: float, *, name: str) -> float:
    """Validate that a readiness polling interval is a positive finite number.

    Args:
        value: Candidate polling sleep interval in seconds.
        name: Parameter name used in error messages.

    Returns:
        The validated positive polling interval as a ``float``.

    Raises:
        ValueError: If ``value`` is a boolean, not numeric, non-finite, or less than or equal to zero.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        msg = f"{name} must be a positive finite number, got {value!r}"
        raise ValueError(msg)
    return float(value)


def _parse_timeout(env_var: str, default: int) -> int:
    """Parse and validate a positive integer timeout from an environment variable.

    Args:
        env_var: Environment variable name to read.
        default: Default timeout in seconds when ``env_var`` is unset.

    Returns:
        The parsed positive integer timeout.

    Raises:
        ValueError: If the configured or default value is not a positive integer.
    """
    raw = os.getenv(env_var)
    if raw is None:
        return _validate_positive_timeout(default, name=env_var)
    try:
        parsed = int(raw)
    except ValueError as exc:
        msg = f"{env_var} must be a positive integer, got {raw!r}"
        raise ValueError(msg) from exc
    return _validate_positive_timeout(parsed, name=env_var)
