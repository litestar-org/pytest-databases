from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_plugin_imports_without_psycopg(pytester: pytest.Pytester) -> None:
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


def test_service_fixture(pytester: pytest.Pytester) -> None:
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


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
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


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
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
