"""Snowflake-compatible Embucket container service fixtures and stdlib HTTP helpers."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

__all__ = [
    "DEFAULT_SNOWFLAKE_IMAGE",
    "SNOWFLAKE_HTTP_PORT",
    "SnowflakeService",
    "check_snowflake_health",
    "embucket_service",
    "provide_snowflake_service",
    "query_snowflake_emulator",
    "snowflake_account",
    "snowflake_database",
    "snowflake_image",
    "snowflake_password",
    "snowflake_role",
    "snowflake_schema",
    "snowflake_service",
    "snowflake_user",
    "snowflake_warehouse",
    "xdist_snowflake_isolation_level",
]

DEFAULT_SNOWFLAKE_IMAGE = "embucket/embucket:latest"
SNOWFLAKE_HTTP_PORT = 3000
_SNOWFLAKE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass
class SnowflakeService(ServiceContainer):
    """Connection metadata and stdlib HTTP query helper for an Embucket Snowflake emulator."""

    user: str
    password: str
    account: str
    database: str
    schema: str
    warehouse: str
    role: str

    @property
    def endpoint(self) -> str:
        """The HTTP base endpoint URL for the Snowflake emulator."""
        return f"http://{self.host}:{self.port}"

    @property
    def connection_kwargs(self) -> dict[str, str | int]:
        """Dictionary of connection parameters compatible with ``snowflake.connector.connect``."""
        return {
            "host": self.host,
            "port": self.port,
            "protocol": "http",
            "user": self.user,
            "password": self.password,
            "account": self.account,
            "database": self.database,
            "schema": self.schema,
            "warehouse": self.warehouse,
            "role": self.role,
        }

    def query(self, sql: str) -> dict[str, Any]:
        """Execute a SQL statement via the Snowflake REST endpoint without a host driver."""
        return query_snowflake_emulator(self.host, self.port, sql)


def check_snowflake_health(host: str, port: int, *, timeout: float = 2.0) -> bool:
    """Probe the Embucket Snowflake emulator HTTP health endpoint using stdlib ``urllib.request``.

    Args:
        host: Mapped container host address.
        port: Mapped container HTTP port.
        timeout: Socket timeout in seconds.

    Returns:
        ``True`` if the emulator responds with HTTP 200, otherwise ``False``.
    """
    for path in ("/health", "/v1/metastore/databases"):
        url = f"http://{host}:{port}{path}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def query_snowflake_emulator(
    host: str,
    port: int,
    sql: str,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Execute a SQL statement against the Embucket Snowflake REST protocol endpoint.

    Args:
        host: Mapped container host address.
        port: Mapped container HTTP port.
        sql: SQL statement to execute.
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed JSON response payload from ``/queries/v1/query-request``.
    """
    url = f"http://{host}:{port}/queries/v1/query-request"
    payload = json.dumps({"sqlText": sql}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": 'Snowflake Token="pytest-databases"',
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body.strip() else {"success": True}
        return parsed if isinstance(parsed, dict) else {"success": True, "data": parsed}


@contextmanager
def provide_snowflake_service(
    container_service: ContainerService,
    snowflake_image: str,
    snowflake_user: str,
    snowflake_password: str,
    snowflake_account: str,
    snowflake_database: str,
    snowflake_schema: str,
    snowflake_warehouse: str,
    snowflake_role: str,
    xdist_snowflake_isolation_level: XdistIsolationLevel,
) -> Generator[SnowflakeService, None, None]:
    """Start and yield a ready Embucket Snowflake-compatible service container.

    Yields:
        A configured SnowflakeService instance.
    """
    worker_num = get_xdist_worker_num()
    name = "snowflake"
    transient = False
    if worker_num is not None and xdist_snowflake_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    def check(service: ServiceContainer) -> bool:
        return check_snowflake_health(service.host, service.port)

    with container_service.run(
        image=snowflake_image,
        name=name,
        container_port=SNOWFLAKE_HTTP_PORT,
        env={
            "EMBUCKET_PORT": str(SNOWFLAKE_HTTP_PORT),
            "NO_COLOR": "true",
        },
        check=check,
        timeout=90,
        pause=0.5,
        transient=transient,
    ) as service:
        if snowflake_schema.lower() != "public":
            db_ident = _validate_snowflake_identifier(snowflake_database)
            schema_ident = _validate_snowflake_identifier(snowflake_schema)
            query_snowflake_emulator(
                service.host,
                service.port,
                f"CREATE SCHEMA IF NOT EXISTS {db_ident}.{schema_ident}",
            )
        yield SnowflakeService(
            container=service.container,
            host=service.host,
            port=service.port,
            user=snowflake_user,
            password=snowflake_password,
            account=snowflake_account,
            database=snowflake_database,
            schema=snowflake_schema,
            warehouse=snowflake_warehouse,
            role=snowflake_role,
        )


@pytest.fixture(scope="session")
def xdist_snowflake_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for the Snowflake emulator."""
    return "database"


@pytest.fixture(scope="session")
def snowflake_image() -> str:
    """Provide the Embucket Snowflake emulator container image."""
    return os.getenv("SNOWFLAKE_IMAGE", DEFAULT_SNOWFLAKE_IMAGE)


@pytest.fixture(scope="session")
def snowflake_user() -> str:
    """Provide the Snowflake test username."""
    return os.getenv("SNOWFLAKE_USER", "embucket")


@pytest.fixture(scope="session")
def snowflake_password() -> str:
    """Provide the Snowflake test password."""
    return os.getenv("SNOWFLAKE_PASSWORD", "embucket")


@pytest.fixture(scope="session")
def snowflake_account() -> str:
    """Provide the Snowflake test account identifier."""
    return os.getenv("SNOWFLAKE_ACCOUNT", "embucket")


@pytest.fixture(scope="session")
def snowflake_database() -> str:
    """Provide the default Snowflake database name."""
    return os.getenv("SNOWFLAKE_DATABASE", "embucket")


@pytest.fixture(scope="session")
def snowflake_schema(xdist_snowflake_isolation_level: XdistIsolationLevel) -> str:
    """Provide a worker-scoped Snowflake schema name."""
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_snowflake_isolation_level == "database":
        return f"public_{worker_num}"
    return os.getenv("SNOWFLAKE_SCHEMA", "public")


@pytest.fixture(scope="session")
def snowflake_warehouse() -> str:
    """Provide the default Snowflake warehouse name."""
    return os.getenv("SNOWFLAKE_WAREHOUSE", "embucket")


@pytest.fixture(scope="session")
def snowflake_role() -> str:
    """Provide the default Snowflake role name."""
    return os.getenv("SNOWFLAKE_ROLE", "sysadmin")


@pytest.fixture(scope="session")
def snowflake_service(
    container_service: ContainerService,
    snowflake_image: str,
    snowflake_user: str,
    snowflake_password: str,
    snowflake_account: str,
    snowflake_database: str,
    snowflake_schema: str,
    snowflake_warehouse: str,
    snowflake_role: str,
    xdist_snowflake_isolation_level: XdistIsolationLevel,
) -> Generator[SnowflakeService, None, None]:
    """Start and yield a ready Embucket Snowflake-compatible service container.

    Yields:
        A configured SnowflakeService instance.
    """
    with provide_snowflake_service(
        container_service=container_service,
        snowflake_image=snowflake_image,
        snowflake_user=snowflake_user,
        snowflake_password=snowflake_password,
        snowflake_account=snowflake_account,
        snowflake_database=snowflake_database,
        snowflake_schema=snowflake_schema,
        snowflake_warehouse=snowflake_warehouse,
        snowflake_role=snowflake_role,
        xdist_snowflake_isolation_level=xdist_snowflake_isolation_level,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def embucket_service(snowflake_service: SnowflakeService) -> SnowflakeService:
    """Alias for ``snowflake_service``."""
    return snowflake_service


def _validate_snowflake_identifier(identifier: str) -> str:
    """Validate a Snowflake database or schema identifier."""
    if not _SNOWFLAKE_IDENTIFIER_PATTERN.match(identifier):
        msg = f"Invalid Snowflake identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier
