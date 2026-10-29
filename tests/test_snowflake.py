"""Tests for Snowflake-compatible Embucket container service fixtures and HTTP helpers."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

from pytest_databases.docker import snowflake
from pytest_databases.docker.snowflake import (
    DEFAULT_SNOWFLAKE_IMAGE,
    SnowflakeService,
    check_snowflake_health,
    provide_snowflake_service,
    query_snowflake_emulator,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    import pytest
    from pytest import MonkeyPatch


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


def test_check_snowflake_health_and_query_emulator(monkeypatch: MonkeyPatch) -> None:
    """Verify check_snowflake_health and query_snowflake_emulator over stdlib urllib.request."""
    visited: list[str] = []

    def fake_urlopen(request: Any, **_kwargs: Any) -> Any:
        visited.append(request.full_url)
        if request.full_url.endswith("/health"):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                email.message.Message(),
                io.BytesIO(b""),
            )
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = json.dumps({"success": True, "data": {"rowset": [["1"]]}}).encode("utf-8")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert check_snowflake_health("127.0.0.1", 3000) is True
    assert visited == [
        "http://127.0.0.1:3000/health",
        "http://127.0.0.1:3000/v1/metastore/databases",
    ]

    result = query_snowflake_emulator("127.0.0.1", 3000, "SELECT 1")
    assert result["success"] is True
    assert visited[-1] == "http://127.0.0.1:3000/queries/v1/query-request"


def test_snowflake_service_metadata(monkeypatch: MonkeyPatch) -> None:
    """Verify SnowflakeService endpoint, connection_kwargs, and query method."""
    service = SnowflakeService(
        container=MagicMock(),
        host="127.0.0.1",
        port=3000,
        user="embucket",
        password="embucket",
        account="embucket",
        database="embucket",
        schema="public",
        warehouse="embucket",
        role="sysadmin",
    )
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

    monkeypatch.setattr(
        "pytest_databases.docker.snowflake.query_snowflake_emulator",
        lambda _h, _p, sql: {"sql": sql, "success": True},
    )
    assert service.query("SELECT 1") == {"sql": "SELECT 1", "success": True}


def test_provide_snowflake_service_provisions_worker_schema(monkeypatch: MonkeyPatch) -> None:
    """Verify provide_snowflake_service provisions non-public worker schemas in the emulator."""
    executed_queries: list[str] = []

    class FakeContainerService:
        def run(self, **_kwargs: object) -> Any:
            @contextmanager
            def _ctx() -> Any:
                yield ServiceContainer(container=MagicMock(), host="127.0.0.1", port=3000)

            return _ctx()

    def fake_query(_host: str, _port: int, sql: str) -> dict[str, Any]:
        executed_queries.append(sql)
        return {"success": True}

    monkeypatch.setattr(snowflake, "get_xdist_worker_num", lambda: 2)
    monkeypatch.setattr(snowflake, "query_snowflake_emulator", fake_query)
    with provide_snowflake_service(
        container_service=cast("Any", FakeContainerService()),
        snowflake_image=DEFAULT_SNOWFLAKE_IMAGE,
        snowflake_user="embucket",
        snowflake_password="embucket",
        snowflake_account="embucket",
        snowflake_database="embucket",
        snowflake_schema="public_2",
        snowflake_warehouse="embucket",
        snowflake_role="sysadmin",
        xdist_snowflake_isolation_level="database",
    ) as service:
        assert service.schema == "public_2"
        assert executed_queries == ["CREATE SCHEMA IF NOT EXISTS embucket.public_2"]


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
