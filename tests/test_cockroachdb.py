"""Tests for CockroachDB container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.cockroachdb import (
    CockroachDBService,
    cockroachdb_driver_opts,
    open_cockroachdb_connection,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.pytester import Pytester


def test_plugin_imports_without_psycopg(pytester: Pytester) -> None:
    """Verify cockroachdb plugin imports cleanly without psycopg installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "psycopg" or name.startswith("psycopg."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.cockroachdb
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_cockroachdb_deprecated_connection_shim() -> None:
    """Verify cockroachdb_connection emits DeprecationWarning and lazily connects with driver_opts."""
    mock_psycopg = MagicMock()
    mock_conn = MagicMock()
    mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
    service = CockroachDBService(
        host="127.0.0.1",
        port=26257,
        container=MagicMock(),
        database="pytest_databases",
        driver_opts={"sslmode": "disable"},
    )
    assert _unwrap_fixture(cockroachdb_driver_opts)() == {"sslmode": "disable"}

    with (
        patch("importlib.import_module", return_value=mock_psycopg) as mock_import,
        pytest.deprecated_call(match="cockroachdb_connection"),
        open_cockroachdb_connection(
            service,
            service.driver_opts,
            fixture_name="cockroachdb_connection",
        ) as conn,
    ):
        assert conn is mock_conn

    mock_import.assert_called_once_with("psycopg")
    mock_psycopg.connect.assert_called_once_with(
        "postgresql://root@127.0.0.1:26257/pytest_databases?sslmode=disable",
    )


def test_service_fixture(pytester: Pytester) -> None:
    """Verify cockroachdb_service executes SQL via the in-container cockroach CLI."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def run_cockroach(service, sql, database=None):
        result = service.container.exec_run([
            "cockroach",
            "sql",
            "--insecure",
            "--host=localhost:26257",
            f"--database={database or service.database}",
            "--format=tsv",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]

    def test(cockroachdb_service):
        assert cockroachdb_service.driver_opts == {"sslmode": "disable"}
        rows = run_cockroach(cockroachdb_service, "SELECT 1")
        assert rows[-1] == "1"
        run_cockroach(cockroachdb_service, "CREATE TABLE IF NOT EXISTS simple_table (the_value INT)")
        run_cockroach(cockroachdb_service, "INSERT INTO simple_table VALUES (1)")
        rows = run_cockroach(cockroachdb_service, "SELECT the_value FROM simple_table")
        assert rows[-1] == "1"
        run_cockroach(cockroachdb_service, "DROP TABLE simple_table")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: Pytester) -> None:
    """Verify cockroachdb_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def run_cockroach(service, sql):
        result = service.container.exec_run([
            "cockroach",
            "sql",
            "--insecure",
            "--host=localhost:26257",
            f"--database={service.database}",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_one(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE TABLE foo (the_value INT)")

    def test_two(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE TABLE foo (the_value INT)")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: Pytester) -> None:
    """Verify cockroachdb_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    @pytest.fixture(scope="session")
    def xdist_cockroachdb_isolation_level():
        return "server"

    def run_cockroach(service, sql, database=None):
        result = service.container.exec_run([
            "cockroach",
            "sql",
            "--insecure",
            "--host=localhost:26257",
            f"--database={database or service.database}",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_one(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE DATABASE db_test", database="defaultdb")

    def test_two(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE DATABASE db_test", database="defaultdb")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__
