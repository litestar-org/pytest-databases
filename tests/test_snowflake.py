"""Tests for Snowflake-compatible Embucket container service fixtures and HTTP helpers."""

from __future__ import annotations

import gzip
import http.server
import json
import os
import socket
import threading
import urllib.parse
from typing import TYPE_CHECKING, Any, Self
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import snowflake
from pytest_databases.docker.snowflake import (
    DEFAULT_SNOWFLAKE_IMAGE,
    SNOWFLAKE_HTTP_PORT,
    SnowflakeService,
    check_snowflake_health,
    login_snowflake_emulator,
    provide_snowflake_service,
    query_snowflake_emulator,
    snowflake_wire_compat,
)
from pytest_databases.helpers import http_request, send_http_request
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch


class FakeEmbucket:
    """Loopback HTTP server emulating the Embucket Snowflake REST endpoints."""

    def __init__(self, *, valid_tokens: set[str] | None = None, query_success: bool = True) -> None:
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.valid_tokens = valid_tokens
        self.query_success = query_success
        self.logins = 0
        self.rowset_factory: Callable[[dict[str, Any]], list[list[Any]]] = lambda _body: [[1]]
        self.responder: Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]] | None = None
        parent = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/health":
                    body = b'{"status":"ok"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b""
                payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
                headers_lower = {k.lower(): v for k, v in self.headers.items()}
                parent.requests.append((self.path, headers_lower, payload))
                split = urllib.parse.urlsplit(self.path)
                if split.path == "/session/v1/login-request":
                    parent.logins += 1
                    resp_payload: dict[str, Any] = {"success": True, "data": {"token": f"token-{parent.logins}"}}
                    self._send_json(200, resp_payload)
                    return
                auth = headers_lower.get("authorization", "")
                if parent.valid_tokens is not None and not any(f'"{token}"' in auth for token in parent.valid_tokens):
                    self._send_json(401, {"success": False, "code": "390104", "message": "Unauthorized"})
                    return
                if parent.responder is not None:
                    status, custom = parent.responder(split.path, payload)
                    self._send_json(status, custom)
                    return
                if not parent.query_success:
                    self._send_json(200, {"success": False, "code": "002003", "message": "table 'missing' not found"})
                    return
                self._send_json(200, {"success": True, "data": {"rowset": parent.rowset_factory(payload)}})

            def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
                _ = (self.command, code, size)

            def _send_json(self, status: int, body_obj: dict[str, Any]) -> None:
                body = json.dumps(body_obj).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.port = int(self.server.server_address[1])
        self._saved_proxy_env: dict[str, str | None] = {}

    def __enter__(self) -> Self:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            self._saved_proxy_env[var] = os.environ.get(var)
            os.environ[var] = "http://127.0.0.1:1"
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5.0)
        finally:
            for var, prev in self._saved_proxy_env.items():
                if prev is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = prev


def _service(**overrides: Any) -> SnowflakeService:
    values: dict[str, Any] = {
        "container": MagicMock(),
        "host": "127.0.0.1",
        "port": 3000,
        "user": "embucket",
        "password": "embucket",
        "account": "embucket",
        "database": "embucket",
        "schema": "public_1",
        "warehouse": "embucket",
        "role": "sysadmin",
    }
    return SnowflakeService(**(values | overrides))


def test_plugin_imports_without_snowflake_clients(pytester: pytest.Pytester) -> None:
    """Ensure the Snowflake module imports cleanly when snowflake packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"snowflake"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.snowflake")
            assert module.SnowflakeService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("healthy", [True, False])
def test_check_snowflake_health_probes_health_endpoint(monkeypatch: MonkeyPatch, healthy: bool) -> None:
    """Readiness is an HTTP 200 from ``/health``."""
    probed: list[str] = []

    def fake_http_get_ok(url: str, *, timeout: float) -> bool:
        probed.append(url)
        return healthy

    monkeypatch.setattr(snowflake, "http_get_ok", fake_http_get_ok)
    assert check_snowflake_health("127.0.0.1", 3000) is healthy
    assert probed == ["http://127.0.0.1:3000/health"]


def test_login_sends_credentials_and_session_context() -> None:
    """Login posts credentials, passes query context, and bypasses ambient proxy environment variables."""
    with FakeEmbucket() as fake:
        token = login_snowflake_emulator(
            "127.0.0.1", fake.port, user="u", password="p", account="a", database="db", schema="s", warehouse="wh"
        )

    assert token == "token-1"
    raw_path, _headers, payload = fake.requests[0]
    url = urllib.parse.urlsplit(raw_path)
    assert url.path == "/session/v1/login-request"
    assert urllib.parse.parse_qs(url.query) == {"databaseName": ["db"], "schemaName": ["s"], "warehouse": ["wh"]}
    data = payload["data"]
    assert (data["LOGIN_NAME"], data["PASSWORD"], data["ACCOUNT_NAME"]) == ("u", "p", "a")


def test_login_reports_rejected_credentials() -> None:
    """A 401 login response raises RuntimeError with the emulator message."""

    class _RejectHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = b'{"success":false,"message":"Invalid auth data","code":"010001"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            _ = (self.command, code, size)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RejectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(RuntimeError, match="Invalid auth data"):
            login_snowflake_emulator(
                "127.0.0.1", int(server.server_address[1]), user="u", password="wrong", account="a"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def test_query_sends_token_and_request_id() -> None:
    """Queries carry the session token and the ``requestId`` query parameter Embucket requires."""
    with FakeEmbucket() as fake:
        result = query_snowflake_emulator("127.0.0.1", fake.port, "SELECT 1", token="abc")

    assert result["data"]["rowset"] == [[1]]
    raw_path, headers, payload = fake.requests[0]
    url = urllib.parse.urlsplit(raw_path)
    assert url.path == "/queries/v1/query-request"
    assert list(urllib.parse.parse_qs(url.query)) == ["requestId"]
    assert headers.get("authorization") == 'Snowflake Token="abc"'
    assert payload == {"sqlText": "SELECT 1"}


def test_query_raises_on_failed_statement() -> None:
    """A ``success: false`` response raises RuntimeError with the emulator message."""
    with FakeEmbucket(query_success=False) as fake, pytest.raises(RuntimeError, match="table 'missing' not found"):
        query_snowflake_emulator("127.0.0.1", fake.port, "SELECT * FROM missing", token="abc")


def test_service_query_logs_in_once_and_caches_token() -> None:
    """``SnowflakeService.query`` logs in with its database and schema and reuses the token."""
    with FakeEmbucket() as fake:
        service = _service(port=fake.port)
        service.query("SELECT 1")
        service.query("SELECT 2")

    assert fake.logins == 1
    login_query = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.requests[0][0]).query)
    assert login_query["databaseName"] == ["embucket"]
    assert login_query["schemaName"] == ["public_1"]
    assert all(req[1].get("authorization") == 'Snowflake Token="token-1"' for req in fake.requests[1:])


def test_service_query_logs_in_again_after_rejected_token() -> None:
    """A 401 for the cached token triggers one new login and a retry."""
    with FakeEmbucket(valid_tokens={"token-2"}) as fake:
        service = _service(port=fake.port)
        assert service.query("SELECT 1")["data"]["rowset"] == [[1]]

    assert fake.logins == 2
    assert fake.requests[-1][1].get("authorization") == 'Snowflake Token="token-2"'


def test_snowflake_service_metadata() -> None:
    """Verify SnowflakeService endpoint and connection_kwargs."""
    service = _service(schema="public")
    assert service.endpoint == "http://127.0.0.1:3000"
    assert service.connection_kwargs == {
        "host": "127.0.0.1",
        "port": 3000,
        "protocol": "http",
        "user": "embucket",
        "password": "embucket",
        "account": "embucket",
        "database": "embucket",
        "schema": "public",
        "warehouse": "embucket",
        "role": "sysadmin",
    }


@pytest.mark.parametrize(
    ("schema", "expected_queries"),
    [("public", []), ("public_2", ["CREATE SCHEMA IF NOT EXISTS embucket.public_2"])],
)
def test_provide_snowflake_service_configures_container_and_schema(
    monkeypatch: MonkeyPatch, schema: str, expected_queries: list[str]
) -> None:
    """The container gets the login user, an in-memory database volume, and the HTTP port; worker schemas are created."""
    executed: list[str] = []

    def record_query(_self: SnowflakeService, sql: str) -> dict[str, Any]:
        executed.append(sql)
        return {"success": True}

    monkeypatch.setattr(SnowflakeService, "query", record_query)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    container_service = MagicMock()
    container_service.run.return_value.__enter__.return_value = MagicMock(host="127.0.0.1", port=40000)

    with provide_snowflake_service(
        container_service=container_service,
        snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
        snowflake_user="alice",
        snowflake_password="secret",
        snowflake_account="embucket",
        snowflake_database="embucket",
        snowflake_schema=schema,
        snowflake_warehouse="embucket",
        snowflake_role="sysadmin",
        xdist_snowflake_isolation_level="database",
    ) as service:
        assert service.schema == schema
        assert service.port != 40000

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["container_port"] == SNOWFLAKE_HTTP_PORT
    assert kwargs["env"] == {
        "BUCKET_PORT": "3000",
        "AUTH_DEMO_USER": "alice",
        "AUTH_DEMO_PASSWORD": "secret",
        "VOLUME_TYPE": "memory",
        "VOLUME_DATABASE": "embucket",
    }
    assert executed == expected_queries


def test_snowflake_wire_proxy_gzip_and_rowset_normalization(monkeypatch: MonkeyPatch) -> None:
    """Loopback proxy decompresses gzip payloads, stringifies rowset cells, and closes socket on teardown."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    with FakeEmbucket() as fake:
        fake.rowset_factory = lambda _body: [[1, 2.5, True, False, None, {"a": 1}, [9]]]
        container_service = MagicMock()
        container_service.run.return_value.__enter__.return_value = MagicMock(host="127.0.0.1", port=fake.port)

        with provide_snowflake_service(
            container_service=container_service,
            snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
            snowflake_user="embucket",
            snowflake_password="embucket",
            snowflake_account="embucket",
            snowflake_database="embucket",
            snowflake_schema="public",
            snowflake_warehouse="embucket",
            snowflake_role="sysadmin",
            xdist_snowflake_isolation_level="database",
            wire_compat=True,
        ) as service:
            proxy_port = service.port
            assert proxy_port != fake.port
            compressed = gzip.compress(json.dumps({"sqlText": "SELECT 42"}).encode("utf-8"))
            status, _headers, body = send_http_request(
                f"{service.endpoint}/queries/v1/query-request?requestId=1",
                method="POST",
                data=compressed,
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
                timeout=5.0,
            )
            assert status == 200
            parsed = json.loads(body.decode("utf-8"))
            assert parsed["data"]["rowset"] == [["1", "2.5", "true", "false", None, '{"a": 1}', "[9]"]]
            assert fake.requests[-1][1].get("content-encoding") is None

        with pytest.raises(OSError), socket.create_connection(("127.0.0.1", proxy_port), timeout=1.0):
            pass


def test_snowflake_wire_proxy_disabled_preserves_raw_rowset(monkeypatch: MonkeyPatch) -> None:
    """``wire_compat=False`` forwards requests straight to the container without stringifying rowset cells."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    with FakeEmbucket() as fake:
        fake.rowset_factory = lambda _body: [[1, 2.5, True, False, None, {"a": 1}, [9]]]
        container_service = MagicMock()
        container_service.run.return_value.__enter__.return_value = MagicMock(host="127.0.0.1", port=fake.port)

        with provide_snowflake_service(
            container_service=container_service,
            snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
            snowflake_user="embucket",
            snowflake_password="embucket",
            snowflake_account="embucket",
            snowflake_database="embucket",
            snowflake_schema="public",
            snowflake_warehouse="embucket",
            snowflake_role="sysadmin",
            xdist_snowflake_isolation_level="database",
            wire_compat=False,
        ) as service:
            assert service.port == fake.port
            raw = service.query("SELECT 1")
            assert raw["data"]["rowset"] == [[1, 2.5, True, False, None, {"a": 1}, [9]]]


def test_snowflake_wire_proxy_lexical_bindings_and_types(monkeypatch: MonkeyPatch) -> None:
    """Proxy expands only unquoted ``?`` placeholders across lexical boundaries and all Snowflake binding types."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    with FakeEmbucket() as fake:
        container_service = MagicMock()
        container_service.run.return_value.__enter__.return_value = MagicMock(host="127.0.0.1", port=fake.port)
        with provide_snowflake_service(
            container_service=container_service,
            snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
            snowflake_user="embucket",
            snowflake_password="embucket",
            snowflake_account="embucket",
            snowflake_database="embucket",
            snowflake_schema="public",
            snowflake_warehouse="embucket",
            snowflake_role="sysadmin",
            xdist_snowflake_isolation_level="database",
            wire_compat=True,
        ) as service:
            sql_text = "SELECT '?' AS s, 'a\\'?' AS e, \"c?1\", $$?$$, ? -- ?\n, /* ? */ ?, ?, ?, ?, ?, ?, ?"
            bindings = {
                "1": {"type": "TEXT", "value": "O'Reilly"},
                "2": {"type": "FIXED", "value": "-19"},
                "3": {"type": "REAL", "value": "3.25"},
                "4": {"type": "BOOLEAN", "value": True},
                "5": {"type": "BOOLEAN", "value": "false"},
                "6": {"type": "NULL", "value": None},
                "7": {"type": "BINARY", "value": "deadbeef"},
                "8": {"type": "TEXT", "value": "hi"},
            }
            payload = json.dumps({"sqlText": sql_text, "bindings": bindings}).encode("utf-8")
            status, _body = http_request(
                f"{service.endpoint}/queries/v1/query-request?requestId=2",
                method="POST",
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=5.0,
            )
            assert status == 200
            _, _hdrs, upstream_payload = fake.requests[-1]
            assert "bindings" not in upstream_payload
            assert upstream_payload["sqlText"] == (
                "SELECT '?' AS s, 'a\\'?' AS e, \"c?1\", $$?$$, 'O''Reilly' -- ?\n"
                ", /* ? */ -19, 3.25, TRUE, FALSE, NULL, X'DEADBEEF', 'hi'"
            )


@pytest.mark.parametrize(
    ("raw_body", "content_encoding"),
    [
        (b"not-gzip", "gzip"),
        (json.dumps({"sqlText": "SELECT ?", "bindings": {"2": {"type": "FIXED", "value": "1"}}}).encode(), None),
        (json.dumps({"sqlText": "SELECT ?", "bindings": {"1": {"type": "FIXED", "value": "1 OR 1=1"}}}).encode(), None),
        (json.dumps({"sqlText": "SELECT ?", "bindings": {"1": {"type": "REAL", "value": "NaN"}}}).encode(), None),
        (json.dumps({"sqlText": "SELECT ?", "bindings": {"1": {"type": "REAL", "value": "Infinity"}}}).encode(), None),
        (json.dumps({"sqlText": "SELECT ?", "bindings": {"1": {"type": "BINARY", "value": "xyz"}}}).encode(), None),
        (json.dumps({"sqlText": "SELECT ?", "bindings": {"1": {"type": "BOOLEAN", "value": "maybe"}}}).encode(), None),
    ],
)
def test_snowflake_wire_proxy_rejects_malformed_requests(
    monkeypatch: MonkeyPatch, raw_body: bytes, content_encoding: str | None
) -> None:
    """Malformed gzip bodies and invalid/injection-like parameter bindings return HTTP 400 without upstream dispatch."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    with FakeEmbucket() as fake:
        container_service = MagicMock()
        container_service.run.return_value.__enter__.return_value = MagicMock(host="127.0.0.1", port=fake.port)
        with provide_snowflake_service(
            container_service=container_service,
            snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
            snowflake_user="embucket",
            snowflake_password="embucket",
            snowflake_account="embucket",
            snowflake_database="embucket",
            snowflake_schema="public",
            snowflake_warehouse="embucket",
            snowflake_role="sysadmin",
            xdist_snowflake_isolation_level="database",
            wire_compat=True,
        ) as service:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if content_encoding is not None:
                headers["Content-Encoding"] = content_encoding
            status, _headers, body = send_http_request(
                f"{service.endpoint}/queries/v1/query-request?requestId=3",
                method="POST",
                data=raw_body,
                headers=headers,
                timeout=5.0,
            )
            assert status == 400
            assert json.loads(body.decode("utf-8"))["success"] is False
            assert fake.requests == []


@pytest.mark.parametrize(("env_val", "expected"), [(None, True), ("0", False), ("false", False), ("true", True)])
def test_snowflake_wire_compat_fixture(monkeypatch: MonkeyPatch, env_val: str | None, expected: bool) -> None:
    """Verify ``snowflake_wire_compat`` reads ``SNOWFLAKE_WIRE_COMPAT`` with default True."""
    if env_val is None:
        monkeypatch.delenv("SNOWFLAKE_WIRE_COMPAT", raising=False)
    else:
        monkeypatch.setenv("SNOWFLAKE_WIRE_COMPAT", env_val)
    assert unwrap_fixture(snowflake_wire_compat)() is expected


def test_provide_snowflake_service_rejects_invalid_identifiers() -> None:
    """Database and schema names are validated before the container starts."""
    container_service = MagicMock()
    with (
        pytest.raises(ValueError, match="Invalid Snowflake identifier"),
        provide_snowflake_service(
            container_service=container_service,
            snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
            snowflake_user="embucket",
            snowflake_password="embucket",
            snowflake_account="embucket",
            snowflake_database="embucket",
            snowflake_schema="bad-schema; DROP",
            snowflake_warehouse="embucket",
            snowflake_role="sysadmin",
            xdist_snowflake_isolation_level="database",
        ),
    ):
        pass
    container_service.run.assert_not_called()


def test_snowflake_contract_fixtures(pytester: pytest.Pytester, monkeypatch: MonkeyPatch) -> None:
    """Verify default values of Snowflake image, credentials, schema, wire_compat, and isolation fixtures."""
    for var in (
        "PYTEST_XDIST_WORKER",
        "SNOWFLAKE_IMAGE",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_WIRE_COMPAT",
    ):
        monkeypatch.delenv(var, raising=False)

    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.snowflake"]

    def test_contract(
        snowflake_image,
        snowflake_user,
        snowflake_password,
        snowflake_account,
        snowflake_database,
        snowflake_schema,
        snowflake_warehouse,
        snowflake_role,
        snowflake_wire_compat,
        xdist_snowflake_isolation_level,
    ) -> None:
        assert snowflake_image == {DEFAULT_SNOWFLAKE_IMAGE!r}
        assert snowflake_user == "embucket"
        assert snowflake_password == "embucket"
        assert snowflake_account == "embucket"
        assert snowflake_database == "embucket"
        assert snowflake_schema == "public"
        assert snowflake_warehouse == "embucket"
        assert snowflake_role == "sysadmin"
        assert snowflake_wire_compat is True
        assert xdist_snowflake_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_snowflake_service_live(pytester: pytest.Pytester, monkeypatch: MonkeyPatch) -> None:
    """``snowflake_service`` starts Embucket, logs in, and runs SQL in the default database and schema."""
    for var in (
        "PYTEST_XDIST_WORKER",
        "SNOWFLAKE_SCHEMA",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.snowflake"]

    def test_service(snowflake_service) -> None:
        assert snowflake_service.query("SELECT 1")["data"]["rowset"] == [["1"]]
        context = snowflake_service.query("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
        assert context["data"]["rowset"] == [["embucket", "public"]]
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.xdist_group(name="snowflake_nested_xdist")
def test_snowflake_service_live_xdist_database_isolation(pytester: pytest.Pytester, monkeypatch: MonkeyPatch) -> None:
    """Under xdist with ``database`` isolation, workers share one container and query their own schema."""
    for var in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_TESTRUNUID", "PYTEST_XDIST_WORKER_COUNT", "SNOWFLAKE_SCHEMA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SNOWFLAKE_RECORD_DIR", str(pytester.path))
    pytester.makepyfile("""
    import json
    import os
    from pathlib import Path

    import pytest

    pytest_plugins = ["pytest_databases.docker.snowflake"]

    @pytest.mark.parametrize("case", [0, 1])
    def test_isolation(snowflake_service, case) -> None:
        worker_id = os.environ["PYTEST_XDIST_WORKER"]
        schema = f"public_{int(worker_id.removeprefix('gw'))}"
        assert snowflake_service.schema == schema
        context = snowflake_service.query("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
        assert context["data"]["rowset"] == [["embucket", schema]]
        snowflake_service.query(f"CREATE TABLE IF NOT EXISTS marker_{case} (worker VARCHAR)")
        snowflake_service.query(f"INSERT INTO marker_{case} VALUES ('{worker_id}')")
        rows = snowflake_service.query(f"SELECT worker FROM embucket.{schema}.marker_{case}")["data"]["rowset"]
        assert rows == [[worker_id]]
        record = {"container_id": snowflake_service.container.id, "schema": schema}
        path = Path(os.environ["SNOWFLAKE_RECORD_DIR"]) / f"snowflake-{worker_id}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "--dist=load", "-vv")
    result.assert_outcomes(passed=2)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in pytester.path.glob("snowflake-gw*.json")]
    assert len(records) == 2
    assert {record["schema"] for record in records} == {"public_0", "public_1"}
    assert len({record["container_id"] for record in records}) == 1


def test_snowflake_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify Snowflake config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker.snowflake import snowflake_schema

    pytest_plugins = ["pytest_databases.docker.snowflake"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_svc = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        with patch("pytest_databases.docker.snowflake.provide_snowflake_service", side_effect=fake_svc):
            assert request.getfixturevalue("xdist_snowflake_isolation_level") == "database"
            assert request.getfixturevalue("snowflake_image")
            assert request.getfixturevalue("snowflake_user") == "embucket"
            assert request.getfixturevalue("snowflake_password") == "embucket"
            assert request.getfixturevalue("snowflake_account") == "embucket"
            assert request.getfixturevalue("snowflake_database") == "embucket"
            assert request.getfixturevalue("snowflake_schema") == "public"
            assert request.getfixturevalue("snowflake_warehouse") == "embucket"
            assert request.getfixturevalue("snowflake_role") == "sysadmin"
            assert request.getfixturevalue("snowflake_wire_compat") is True
            assert request.getfixturevalue("snowflake_service") is mock_svc

        with patch("pytest_databases.docker.snowflake.get_xdist_worker_num", return_value=2):
            fn = getattr(snowflake_schema, "__wrapped__", snowflake_schema)
            assert fn("database") == "public_2"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
