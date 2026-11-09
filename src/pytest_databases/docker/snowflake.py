"""Snowflake-compatible Embucket container service fixtures and stdlib HTTP helpers.

Embucket always requires authentication: clients log in through ``POST /session/v1/login-request`` and send the
returned session token as ``Authorization: Snowflake Token="<token>"`` on ``/queries/v1/query-request``.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num, http_get_ok
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

__all__ = (
    "DEFAULT_SNOWFLAKE_IMAGE",
    "SNOWFLAKE_HTTP_PORT",
    "SnowflakeService",
    "check_snowflake_health",
    "login_snowflake_emulator",
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
)

DEFAULT_SNOWFLAKE_IMAGE = "embucket/embucket:0.2.2"
SNOWFLAKE_HTTP_PORT = 3000
_SNOWFLAKE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_CLIENT_APP_ID = "pytest-databases"


@dataclass
class SnowflakeService(ServiceContainer):
    """Connection metadata and stdlib HTTP query helper for an Embucket Snowflake emulator.

    ``query()`` logs in on first use with the service credentials, database, schema, and warehouse, caches the session
    token, and logs in again once when the emulator rejects the token.
    """

    user: str
    password: str
    account: str
    database: str
    schema: str
    warehouse: str
    role: str
    _token: str | None = field(default=None, init=False, repr=False, compare=False)

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

    def login(self) -> str:
        """Log in to the emulator, cache the session token, and return it.

        The session's current database and schema are ``database`` and ``schema``.
        """
        self._token = login_snowflake_emulator(
            self.host,
            self.port,
            user=self.user,
            password=self.password,
            account=self.account,
            database=self.database,
            schema=self.schema,
            warehouse=self.warehouse,
        )
        return self._token

    def query(self, sql: str) -> dict[str, Any]:
        """Execute a SQL statement in this service's database and schema without a host driver.

        Returns:
            The JSON response of a successful statement; ``response["data"]["rowset"]`` holds the rows.
        """
        token = self._token or self.login()
        try:
            return query_snowflake_emulator(self.host, self.port, sql, token=token)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
            exc.close()
        return query_snowflake_emulator(self.host, self.port, sql, token=self.login())


def check_snowflake_health(host: str, port: int, *, timeout: float = 2.0) -> bool:
    """Return whether the Embucket ``/health`` endpoint answers HTTP 200.

    Args:
        host: Mapped container host address.
        port: Mapped container HTTP port.
        timeout: Socket timeout in seconds.

    Returns:
        ``True`` if the emulator responds with HTTP 200, otherwise ``False``.
    """
    return http_get_ok(f"http://{host}:{port}/health", timeout=timeout)


def login_snowflake_emulator(
    host: str,
    port: int,
    *,
    user: str,
    password: str,
    account: str,
    database: str | None = None,
    schema: str | None = None,
    warehouse: str | None = None,
    timeout: float = 5.0,
) -> str:
    """Log in to an Embucket Snowflake emulator and return the session token.

    Args:
        host: Mapped container host address.
        port: Mapped container HTTP port.
        user: Login name.
        password: Password.
        account: Account name.
        database: Current database of the new session.
        schema: Current schema of the new session.
        warehouse: Warehouse of the new session.
        timeout: HTTP request timeout in seconds.

    Returns:
        The session token to send as ``Authorization: Snowflake Token="<token>"``.

    Raises:
        RuntimeError: If the emulator rejects the credentials.
    """
    params = {
        key: value
        for key, value in (("databaseName", database), ("schemaName", schema), ("warehouse", warehouse))
        if value is not None
    }
    query_string = f"?{urllib.parse.urlencode(params)}" if params else ""
    body = {
        "data": {
            "CLIENT_APP_ID": _CLIENT_APP_ID,
            "CLIENT_APP_VERSION": "1.0",
            "ACCOUNT_NAME": account,
            "LOGIN_NAME": user,
            "PASSWORD": password,
            "CLIENT_ENVIRONMENT": {},
            "SESSION_PARAMETERS": {},
        }
    }
    url = f"http://{host}:{port}/session/v1/login-request{query_string}"
    try:
        response = _post_json(url, body, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise
        with exc:
            detail = exc.read().decode("utf-8", errors="replace")
        msg = f"Embucket login for user {user!r} failed: HTTP 401 {detail}"
        raise RuntimeError(msg) from None
    token = (response.get("data") or {}).get("token") if response.get("success") else None
    if not token:
        msg = f"Embucket login for user {user!r} failed: {response.get('message')}"
        raise RuntimeError(msg)
    return str(token)


def query_snowflake_emulator(
    host: str,
    port: int,
    sql: str,
    *,
    token: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Execute a SQL statement against the Embucket Snowflake REST endpoint ``/queries/v1/query-request``.

    Args:
        host: Mapped container host address.
        port: Mapped container HTTP port.
        sql: SQL statement to execute.
        token: Session token from ``login_snowflake_emulator``.
        timeout: HTTP request timeout in seconds.

    Returns:
        The JSON response payload; ``response["data"]["rowset"]`` holds the rows.

    Raises:
        RuntimeError: If the emulator reports that the statement failed.
        urllib.error.HTTPError: If the emulator rejects the request, for example with 401 for an expired token.
    """
    query_string = urllib.parse.urlencode({"requestId": str(uuid.uuid4())})
    response = _post_json(
        f"http://{host}:{port}/queries/v1/query-request?{query_string}",
        {"sqlText": sql},
        timeout=timeout,
        headers={"Authorization": f'Snowflake Token="{token}"'},
    )
    if not response.get("success"):
        msg = f"Embucket query failed ({response.get('code')}): {response.get('message')}: {sql}"
        raise RuntimeError(msg)
    return response


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

    The container seeds an in-memory volume with ``snowflake_database`` and its ``public`` schema, and its login user
    is ``snowflake_user`` / ``snowflake_password``. A schema other than ``public`` is created before the service is
    yielded.

    Yields:
        A configured SnowflakeService instance.
    """
    db_ident = _validate_snowflake_identifier(snowflake_database)
    schema_ident = _validate_snowflake_identifier(snowflake_schema)
    worker_num = get_xdist_worker_num()
    name = "snowflake"
    transient = False
    if worker_num is not None and xdist_snowflake_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    with container_service.run(
        image=snowflake_image,
        name=name,
        container_port=SNOWFLAKE_HTTP_PORT,
        env={
            "BUCKET_PORT": str(SNOWFLAKE_HTTP_PORT),
            "AUTH_DEMO_USER": snowflake_user,
            "AUTH_DEMO_PASSWORD": snowflake_password,
            "VOLUME_TYPE": "memory",
            "VOLUME_DATABASE": snowflake_database,
        },
        check=_is_snowflake_ready,
        timeout=90,
        pause=0.5,
        transient=transient,
    ) as container:
        service = SnowflakeService(
            container=container.container,
            host=container.host,
            port=container.port,
            user=snowflake_user,
            password=snowflake_password,
            account=snowflake_account,
            database=snowflake_database,
            schema=snowflake_schema,
            warehouse=snowflake_warehouse,
            role=snowflake_role,
        )
        if schema_ident.lower() != "public":
            service.query(f"CREATE SCHEMA IF NOT EXISTS {db_ident}.{schema_ident}")
        yield service


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
    """Provide the Snowflake login name; the container is started with it as its login user."""
    return os.getenv("SNOWFLAKE_USER", "embucket")


@pytest.fixture(scope="session")
def snowflake_password() -> str:
    """Provide the Snowflake login password; the container is started with it as its login password."""
    return os.getenv("SNOWFLAKE_PASSWORD", "embucket")


@pytest.fixture(scope="session")
def snowflake_account() -> str:
    """Provide the Snowflake test account identifier."""
    return os.getenv("SNOWFLAKE_ACCOUNT", "embucket")


@pytest.fixture(scope="session")
def snowflake_database() -> str:
    """Provide the Snowflake database name seeded in the container."""
    return os.getenv("SNOWFLAKE_DATABASE", "embucket")


@pytest.fixture(scope="session")
def snowflake_schema(xdist_snowflake_isolation_level: XdistIsolationLevel) -> str:
    """Provide the Snowflake schema; ``public_<worker>`` under xdist with ``database`` isolation."""
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


def _post_json(
    url: str, payload: dict[str, Any], *, timeout: float, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """POST a JSON document and return the decoded JSON object response."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    parsed = json.loads(body) if body.strip() else {}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _is_snowflake_ready(service: ServiceContainer) -> bool:
    """Return ``True`` when the Embucket ``/health`` endpoint answers HTTP 200."""
    return check_snowflake_health(service.host, service.port)


def _validate_snowflake_identifier(identifier: str) -> str:
    """Validate a Snowflake database or schema identifier."""
    if not _SNOWFLAKE_IDENTIFIER_PATTERN.match(identifier):
        msg = f"Invalid Snowflake identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier
