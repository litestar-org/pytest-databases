"""Tests for Snowflake-compatible Embucket container service fixtures and HTTP helpers."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any
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
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


class FakeEmbucket:
    """Record ``urlopen`` requests and answer them like the Embucket REST endpoints."""

    def __init__(self, *, valid_tokens: set[str] | None = None, query_success: bool = True) -> None:
        self.requests: list[urllib.request.Request] = []
        self.valid_tokens = valid_tokens
        self.query_success = query_success
        self.logins = 0

    def __call__(self, request: urllib.request.Request, **_kwargs: Any) -> Any:
        self.requests.append(request)
        path = urllib.parse.urlsplit(request.full_url).path
        if path == "/session/v1/login-request":
            self.logins += 1
            return _response({"success": True, "data": {"token": f"token-{self.logins}"}})
        auth = request.get_header("Authorization") or ""
        if self.valid_tokens is not None and not any(f'"{token}"' in auth for token in self.valid_tokens):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", email.message.Message(), io.BytesIO())
        if not self.query_success:
            return _response({"success": False, "code": "002003", "message": "table 'missing' not found"})
        return _response({"success": True, "data": {"rowset": [[1]]}})


def _response(payload: dict[str, Any]) -> Any:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


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


def test_login_sends_credentials_and_session_context(monkeypatch: MonkeyPatch) -> None:
    """Login posts the credentials and passes database, schema, and warehouse as query parameters."""
    fake = FakeEmbucket()
    monkeypatch.setattr(urllib.request, "urlopen", fake)

    token = login_snowflake_emulator(
        "127.0.0.1", 3000, user="u", password="p", account="a", database="db", schema="s", warehouse="wh"
    )

    assert token == "token-1"
    request = fake.requests[0]
    url = urllib.parse.urlsplit(request.full_url)
    assert url.path == "/session/v1/login-request"
    assert urllib.parse.parse_qs(url.query) == {"databaseName": ["db"], "schemaName": ["s"], "warehouse": ["wh"]}
    data = json.loads(request.data)["data"]  # type: ignore[arg-type]
    assert (data["LOGIN_NAME"], data["PASSWORD"], data["ACCOUNT_NAME"]) == ("u", "p", "a")


def test_login_reports_rejected_credentials(monkeypatch: MonkeyPatch) -> None:
    """A 401 login response raises RuntimeError with the emulator message."""
    body = b'{"success":false,"message":"Invalid auth data","code":"010001"}'

    def rejecting_urlopen(request: urllib.request.Request, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", email.message.Message(), io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", rejecting_urlopen)
    with pytest.raises(RuntimeError, match="Invalid auth data"):
        login_snowflake_emulator("127.0.0.1", 3000, user="u", password="wrong", account="a")


def test_query_sends_token_and_request_id(monkeypatch: MonkeyPatch) -> None:
    """Queries carry the session token and the ``requestId`` query parameter Embucket requires."""
    fake = FakeEmbucket()
    monkeypatch.setattr(urllib.request, "urlopen", fake)

    result = query_snowflake_emulator("127.0.0.1", 3000, "SELECT 1", token="abc")

    assert result["data"]["rowset"] == [[1]]
    request = fake.requests[0]
    url = urllib.parse.urlsplit(request.full_url)
    assert url.path == "/queries/v1/query-request"
    assert list(urllib.parse.parse_qs(url.query)) == ["requestId"]
    assert request.get_header("Authorization") == 'Snowflake Token="abc"'
    assert json.loads(request.data) == {"sqlText": "SELECT 1"}  # type: ignore[arg-type]


def test_query_raises_on_failed_statement(monkeypatch: MonkeyPatch) -> None:
    """A ``success: false`` response raises RuntimeError with the emulator message."""
    monkeypatch.setattr(urllib.request, "urlopen", FakeEmbucket(query_success=False))
    with pytest.raises(RuntimeError, match="table 'missing' not found"):
        query_snowflake_emulator("127.0.0.1", 3000, "SELECT * FROM missing", token="abc")


def test_service_query_logs_in_once_and_caches_token(monkeypatch: MonkeyPatch) -> None:
    """``SnowflakeService.query`` logs in with its database and schema and reuses the token."""
    fake = FakeEmbucket()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    service = _service()

    service.query("SELECT 1")
    service.query("SELECT 2")

    assert fake.logins == 1
    login_query = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.requests[0].full_url).query)
    assert login_query["databaseName"] == ["embucket"]
    assert login_query["schemaName"] == ["public_1"]
    assert all(request.get_header("Authorization") == 'Snowflake Token="token-1"' for request in fake.requests[1:])


def test_service_query_logs_in_again_after_rejected_token(monkeypatch: MonkeyPatch) -> None:
    """A 401 for the cached token triggers one new login and a retry."""
    fake = FakeEmbucket(valid_tokens={"token-2"})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    service = _service()

    assert service.query("SELECT 1")["data"]["rowset"] == [[1]]
    assert fake.logins == 2
    assert fake.requests[-1].get_header("Authorization") == 'Snowflake Token="token-2"'


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
    """Verify default values of Snowflake image, credentials, schema, and isolation fixtures."""
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
        assert snowflake_service.query("SELECT 1")["data"]["rowset"] == [[1]]
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
            assert request.getfixturevalue("snowflake_service") is mock_svc

        with patch("pytest_databases.docker.snowflake.get_xdist_worker_num", return_value=2):
            fn = getattr(snowflake_schema, "__wrapped__", snowflake_schema)
            assert fn("database") == "public_2"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
