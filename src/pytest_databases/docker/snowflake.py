"""Snowflake-compatible Embucket container service fixtures and stdlib HTTP helpers.

Embucket always requires authentication: clients log in through ``POST /session/v1/login-request`` and send the
returned session token as ``Authorization: Snowflake Token="<token>"`` on ``/queries/v1/query-request``.
"""

from __future__ import annotations

import decimal
import email.message
import gzip
import http.client
import http.server
import io
import json
import math
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import (
    TRUE_VALUES,
    get_xdist_worker_num,
    http_get_ok,
    http_request,
    read_http_handler_body,
    send_http_request,
)
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

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
    "snowflake_wire_compat",
    "xdist_snowflake_isolation_level",
)

DEFAULT_SNOWFLAKE_IMAGE = "embucket/embucket:0.2.2"
SNOWFLAKE_HTTP_PORT = 3000
_SNOWFLAKE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SNOWFLAKE_HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]*$")
_HOP_BY_HOP_REQUEST_HEADERS = frozenset({
    "host",
    "content-length",
    "content-encoding",
    "connection",
    "transfer-encoding",
    "accept-encoding",
})
_HOP_BY_HOP_RESPONSE_HEADERS = frozenset({"transfer-encoding", "content-encoding", "content-length", "connection"})
_CLIENT_APP_ID = "pytest-databases"


class _InvalidSnowflakeRequestError(ValueError):
    """Raised when a Snowflake REST v1 payload carries malformed gzip data or invalid bindings."""


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
    *,
    wire_compat: bool = True,
) -> Generator[SnowflakeService, None, None]:
    """Start and yield a ready Embucket Snowflake-compatible service container.

    The container seeds an in-memory volume with ``snowflake_database`` and its ``public`` schema, and its login user
    is ``snowflake_user`` / ``snowflake_password``. A schema other than ``public`` is created before the service is
    yielded. When ``wire_compat`` is ``True``, the container is fronted by an ephemeral stdlib loopback proxy that
    translates gzip request bodies, ``?`` SQL bindings, and stringified ``rowset`` cells.

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
        if wire_compat:
            with _start_snowflake_wire_proxy(container.host, container.port) as (proxy_host, proxy_port):
                service = SnowflakeService(
                    container=container.container,
                    host=proxy_host,
                    port=proxy_port,
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
        else:
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
def snowflake_wire_compat() -> bool:
    """Return whether ``snowflake_service`` enables the Snowflake REST v1 wire-compatibility proxy."""
    raw = os.getenv("SNOWFLAKE_WIRE_COMPAT")
    if raw is None:
        return True
    return raw.strip().lower() in TRUE_VALUES


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
    snowflake_wire_compat: bool,
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
        wire_compat=snowflake_wire_compat,
    ) as service:
        yield service


def _post_json(
    url: str, payload: dict[str, Any], *, timeout: float, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """POST a JSON document and return the decoded JSON object response."""
    status, body = http_request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
        timeout=timeout,
    )
    if status >= 400:
        raise urllib.error.HTTPError(url, status, f"HTTP {status}", email.message.Message(), io.BytesIO(body))
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


def _scan_quoted_or_comment_token(sql: str, index: int) -> tuple[str, int] | None:
    """Consume one quoted literal, dollar-quoted block, or comment starting at ``index``."""
    length = len(sql)
    char = sql[index]
    if char == "'":
        cursor = index + 1
        while cursor < length:
            if sql[cursor] == "\\" and cursor + 1 < length:
                cursor += 2
            elif sql[cursor] == "'":
                if cursor + 1 < length and sql[cursor + 1] == "'":
                    cursor += 2
                else:
                    cursor += 1
                    break
            else:
                cursor += 1
        return sql[index:cursor], cursor
    if char == '"':
        cursor = index + 1
        while cursor < length:
            if sql[cursor] == '"':
                if cursor + 1 < length and sql[cursor + 1] == '"':
                    cursor += 2
                else:
                    cursor += 1
                    break
            else:
                cursor += 1
        return sql[index:cursor], cursor
    if sql.startswith("$$", index):
        closing = sql.find("$$", index + 2)
        cursor = length if closing == -1 else closing + 2
        return sql[index:cursor], cursor
    if sql.startswith("--", index):
        newline = sql.find("\n", index + 2)
        cursor = length if newline == -1 else newline + 1
        return sql[index:cursor], cursor
    if sql.startswith("/*", index):
        closing = sql.find("*/", index + 2)
        cursor = length if closing == -1 else closing + 2
        return sql[index:cursor], cursor
    return None


def _render_snowflake_numeric_binding(raw_value: Any, binding_type: str) -> str:
    """Validate and format a ``FIXED`` or ``REAL`` Snowflake parameter binding."""
    if isinstance(raw_value, bool):
        msg = f"Invalid {binding_type} binding value: booleans are not numeric"
        raise _InvalidSnowflakeRequestError(msg)
    if isinstance(raw_value, int):
        return str(raw_value)
    if isinstance(raw_value, float):
        if not math.isfinite(raw_value):
            msg = f"Non-finite {binding_type} binding value: {raw_value!r}"
            raise _InvalidSnowflakeRequestError(msg)
        return repr(raw_value)
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            msg = f"Empty {binding_type} binding value"
            raise _InvalidSnowflakeRequestError(msg)
        try:
            dec = decimal.Decimal(stripped)
        except decimal.InvalidOperation as exc:
            msg = f"Invalid {binding_type} binding value {raw_value!r}: {exc}"
            raise _InvalidSnowflakeRequestError(msg) from exc
        if not dec.is_finite():
            msg = f"Non-finite {binding_type} binding value: {raw_value!r}"
            raise _InvalidSnowflakeRequestError(msg)
        return format(dec, "f")
    msg = f"Unsupported {binding_type} binding value type: {type(raw_value).__name__}"
    raise _InvalidSnowflakeRequestError(msg)


def _render_snowflake_binding(entry: Any) -> str:
    """Validate and render a single Snowflake REST v1 binding dictionary entry into a SQL literal."""
    if not isinstance(entry, dict):
        msg = f"Expected binding entry object, got {type(entry).__name__}"
        raise _InvalidSnowflakeRequestError(msg)
    binding_type = str(entry.get("type", "TEXT")).upper()
    raw_value = entry.get("value")
    if raw_value is None or binding_type == "NULL":
        return "NULL"
    if binding_type == "BOOLEAN":
        if isinstance(raw_value, bool):
            return "TRUE" if raw_value else "FALSE"
        normalized = str(raw_value).strip().lower()
        if normalized in {"true", "1"}:
            return "TRUE"
        if normalized in {"false", "0"}:
            return "FALSE"
        msg = f"Invalid BOOLEAN binding value: {raw_value!r}"
        raise _InvalidSnowflakeRequestError(msg)
    if binding_type in {"FIXED", "REAL"}:
        return _render_snowflake_numeric_binding(raw_value, binding_type)
    if binding_type == "BINARY":
        if not isinstance(raw_value, str) or len(raw_value) % 2 != 0 or not _SNOWFLAKE_HEX_PATTERN.match(raw_value):
            msg = f"Invalid BINARY hex binding value: {raw_value!r}"
            raise _InvalidSnowflakeRequestError(msg)
        return f"X'{raw_value.upper()}'"
    escaped = str(raw_value).replace("'", "''")
    return f"'{escaped}'"


def _substitute_snowflake_bindings(sql: str, bindings: Mapping[str, Any]) -> str:
    """Replace unquoted ``?`` parameter placeholders in ``sql`` with validated literals from ``bindings``."""
    parts: list[str] = []
    index = 0
    length = len(sql)
    bind_index = 0
    while index < length:
        token = _scan_quoted_or_comment_token(sql, index)
        if token is not None:
            segment, next_index = token
            parts.append(segment)
            index = next_index
            continue
        char = sql[index]
        if char == "?":
            bind_index += 1
            key = str(bind_index)
            if key not in bindings:
                msg = f"Missing Snowflake parameter binding for placeholder index {key}"
                raise _InvalidSnowflakeRequestError(msg)
            parts.append(_render_snowflake_binding(bindings[key]))
            index += 1
            continue
        parts.append(char)
        index += 1
    return "".join(parts)


def _stringify_rowset_cell(cell: Any) -> str | None:
    """Normalize a single Embucket ``rowset`` cell value to match Snowflake REST v1 string encoding."""
    if cell is None:
        return None
    if isinstance(cell, bool):
        return "true" if cell else "false"
    if isinstance(cell, (dict, list)):
        return json.dumps(cell)
    return str(cell)


def _stringify_snowflake_rowsets(payload: dict[str, Any]) -> bool:
    """Normalize top-level and ``data.rowset`` arrays in ``payload`` in-place, returning True when mutated."""
    mutated = False
    targets: list[dict[str, Any]] = [payload]
    nested = payload.get("data")
    if isinstance(nested, dict):
        targets.append(nested)
    for target in targets:
        rowset = target.get("rowset")
        if isinstance(rowset, list):
            target["rowset"] = [
                [_stringify_rowset_cell(cell) for cell in row] if isinstance(row, list) else row for row in rowset
            ]
            mutated = True
    return mutated


class _SnowflakeWireHTTPServer(http.server.ThreadingHTTPServer):
    """Daemon multi-threaded loopback server forwarding requests to an Embucket container."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, upstream_host: str, upstream_port: int) -> None:
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        super().__init__(("127.0.0.1", 0), _SnowflakeWireHandler)


class _SnowflakeWireHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler translating Snowflake REST v1 requests and responses."""

    def do_GET(self) -> None:
        """Forward a GET request."""
        self._forward_request()

    def do_POST(self) -> None:
        """Forward a POST request, rewriting gzipped SQL queries and response rowsets."""
        self._forward_request()

    def do_PUT(self) -> None:
        """Forward a PUT request."""
        self._forward_request()

    def do_PATCH(self) -> None:
        """Forward a PATCH request."""
        self._forward_request()

    def do_DELETE(self) -> None:
        """Forward a DELETE request."""
        self._forward_request()

    def do_HEAD(self) -> None:
        """Forward a HEAD request."""
        self._forward_request()

    def do_OPTIONS(self) -> None:
        """Forward an OPTIONS request."""
        self._forward_request()

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Suppress HTTP access logging during test runs."""
        _ = (self.command, code, size)

    def _send_json_error(self, status: int, code: str, message: str) -> None:
        body = json.dumps({"success": False, "code": code, "message": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _prepare_upstream_body(self) -> bytes:
        try:
            raw_body = read_http_handler_body(self.headers, self.rfile)
        except ValueError as exc:
            msg = f"Invalid HTTP request body: {exc}"
            raise _InvalidSnowflakeRequestError(msg) from exc
        content_encoding = self.headers.get("Content-Encoding", "")
        if "gzip" in content_encoding.lower():
            try:
                raw_body = gzip.decompress(raw_body)
            except (OSError, EOFError) as exc:
                msg = f"Invalid gzip request body: {exc}"
                raise _InvalidSnowflakeRequestError(msg) from exc
        if self.command != "POST" or urllib.parse.urlsplit(self.path).path != "/queries/v1/query-request":
            return raw_body
        if not raw_body.strip():
            return raw_body
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = f"Invalid JSON request payload: {exc}"
            raise _InvalidSnowflakeRequestError(msg) from exc
        if not isinstance(payload, dict):
            return raw_body
        if "bindings" in payload:
            bindings = payload.pop("bindings")
            if bindings is not None:
                if not isinstance(bindings, dict):
                    msg = "Snowflake request 'bindings' must be a JSON object"
                    raise _InvalidSnowflakeRequestError(msg)
                if bindings and isinstance(payload.get("sqlText"), str):
                    payload["sqlText"] = _substitute_snowflake_bindings(payload["sqlText"], bindings)
            return json.dumps(payload).encode("utf-8")
        return raw_body

    def _forward_request(self) -> None:
        server = self.server
        if not isinstance(server, _SnowflakeWireHTTPServer):
            msg = f"Unexpected server type: {type(server).__name__}"
            raise TypeError(msg)
        try:
            outgoing_body = self._prepare_upstream_body()
        except _InvalidSnowflakeRequestError as exc:
            self._send_json_error(400, "000400", str(exc))
            return
        outgoing_headers = {
            key: value for key, value in self.headers.items() if key.lower() not in _HOP_BY_HOP_REQUEST_HEADERS
        }
        if outgoing_body or self.command in {"POST", "PUT", "PATCH"}:
            outgoing_headers["Content-Length"] = str(len(outgoing_body))
        upstream_url = f"http://{server.upstream_host}:{server.upstream_port}{self.path}"
        request_data = outgoing_body if outgoing_body or self.command in {"POST", "PUT", "PATCH"} else None
        upstream_req = urllib.request.Request(
            upstream_url,
            data=request_data,
            headers=outgoing_headers,
            method=self.command,
        )
        try:
            status, resp_headers, resp_body = send_http_request(upstream_req, timeout=30.0)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            self._send_json_error(502, "000502", str(exc))
            return
        if resp_body:
            try:
                parsed = json.loads(resp_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict) and _stringify_snowflake_rowsets(parsed):
                resp_body = json.dumps(parsed).encode("utf-8")
        self.send_response(status)
        for key, value in resp_headers.items():
            if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        if self.command != "HEAD" and resp_body:
            self.wfile.write(resp_body)


@contextmanager
def _start_snowflake_wire_proxy(upstream_host: str, upstream_port: int) -> Generator[tuple[str, int], None, None]:
    """Start the ephemeral loopback REST v1 wire-compatibility proxy for Embucket.

    Yields:
        Tuple of ``(host, port)`` for the bound loopback proxy socket.
    """
    server = _SnowflakeWireHTTPServer(upstream_host, upstream_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
