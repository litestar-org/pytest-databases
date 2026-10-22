"""Oracle database container service fixtures and per-worker schema isolation."""

from __future__ import annotations

import contextlib
import shlex
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
    "ORACLE_PASSWORD",
    "ORACLE_SYSTEM_PASSWORD",
    "ORACLE_USER",
    "OracleService",
    "ensure_oracle_user",
    "oracle_18c_image",
    "oracle_18c_service",
    "oracle_18c_service_name",
    "oracle_23ai_image",
    "oracle_23ai_service",
    "oracle_23ai_service_name",
    "oracle_password",
    "oracle_service",
    "oracle_system_password",
    "oracle_user",
    "provide_oracle_service",
    "xdist_oracle_isolation_level",
)

ORACLE_USER = "app"
ORACLE_PASSWORD = "super-secret"
ORACLE_SYSTEM_PASSWORD = "super-secret"


@dataclass
class OracleService(ServiceContainer):
    """Container handle with administrative and application credentials for Oracle."""

    user: str
    password: str
    system_password: str
    service_name: str


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


@pytest.fixture(scope="session")
def xdist_oracle_isolation_level() -> XdistIsolationLevel:
    """Determine Oracle xdist isolation mode (database or server)."""
    return "database"


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_image() -> str:
    """Container image for Oracle Database 23ai Free."""
    return "gvenzl/oracle-free:23-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service_name() -> str:
    """Default PDB service name for Oracle Database 23ai Free."""
    return "FREEPDB1"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_image() -> str:
    """Container image for Oracle Database 18c XE."""
    return "gvenzl/oracle-xe:18-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service_name() -> str:
    """Default PDB service name for Oracle Database 18c XE."""
    return "xepdb1"


@pytest.fixture(autouse=False, scope="session")
def oracle_user() -> str:
    """Default application username for Oracle."""
    return ORACLE_USER


@pytest.fixture(autouse=False, scope="session")
def oracle_password() -> str:
    """Default application password for Oracle."""
    return ORACLE_PASSWORD


@pytest.fixture(autouse=False, scope="session")
def oracle_system_password() -> str:
    """Default administrative SYS password for Oracle."""
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
def oracle_service(oracle_23ai_service: OracleService) -> OracleService:
    """Alias for the latest default Oracle service (23ai)."""
    return oracle_23ai_service


def _normalize_sqlplus_statement(sql: str) -> str:
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
