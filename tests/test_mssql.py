"""Tests for Microsoft SQL Server container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker.mssql import (
    exec_sqlcmd,
    mssql_2022_image,
    mssql_2025_image,
)
from tests.conftest import PLATFORM_PROCESSOR

if TYPE_CHECKING:
    from collections.abc import Callable


def test_plugin_imports_without_pymssql(pytester: pytest.Pytester) -> None:
    """Verify mssql plugin imports cleanly without pymssql installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pymssql":
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.mssql
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_mssql_sqlcmd_fallback_and_images() -> None:
    """Verify exec_sqlcmd falls back across sqlcmd binary locations and image fixtures exist."""
    assert _unwrap_fixture(mssql_2022_image)() == "mcr.microsoft.com/mssql/server:2022-latest"
    assert _unwrap_fixture(mssql_2025_image)() == "mcr.microsoft.com/mssql/server:2025-latest"

    mock_container = MagicMock()
    mock_container.exec_run.side_effect = [
        MagicMock(exit_code=127, output=b"executable file not found"),
        MagicMock(exit_code=0, output=b"1\n"),
    ]
    exit_code, output = exec_sqlcmd(mock_container, "SELECT 1")
    assert exit_code == 0
    assert output == b"1\n"
    assert mock_container.exec_run.call_count == 2
    first_cmd = mock_container.exec_run.call_args_list[0].args[0]
    second_cmd = mock_container.exec_run.call_args_list[1].args[0]
    assert first_cmd[0] == "/opt/mssql-tools18/bin/sqlcmd"
    assert second_cmd[0] == "/opt/mssql-tools/bin/sqlcmd"


@pytest.fixture(scope="module")
def mssql_test_helpers() -> str:
    """Return shared SQL Server sqlcmd test helper code.

    Returns:
        Helper Python source code string.
    """
    return """
    def run_mssql(service, sql, database=None):
        prefix = "" if sql.lstrip().upper().startswith(("ALTER", "CREATE", "DROP")) else "SET NOCOUNT ON; "
        result = service.container.exec_run([
            "/opt/mssql-tools18/bin/sqlcmd",
            "-C",
            "-b",
            "-S",
            "localhost,1433",
            "-U",
            service.user,
            "-P",
            service.password,
            "-d",
            database or service.database,
            "-h",
            "-1",
            "-W",
            "-Q",
            f"{prefix}{sql}",
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]
    """


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="SQL Server container image is not supported on ARM")
def test_service_fixture(pytester: pytest.Pytester, mssql_test_helpers: str) -> None:
    """Verify mssql_service starts and executes T-SQL queries."""
    pytester.makepyfile(f"""
    import pytest

    pytest_plugins = ["pytest_databases.docker.mssql"]

    @pytest.fixture(scope="session")
    def mssql_user():
        return "custom_mssql_user"

    @pytest.fixture(scope="session")
    def mssql_password():
        return "Custom-secret1"

    @pytest.fixture(scope="session")
    def mssql_database():
        return "custom_mssql_database"

    {mssql_test_helpers}

    def test(mssql_service):
        assert mssql_service.user == "custom_mssql_user"
        assert mssql_service.password == "Custom-secret1"
        assert mssql_service.database == "custom_mssql_database"
        assert run_mssql(mssql_service, "SELECT 1 AS is_available") == ["1"]
        run_mssql(mssql_service, "CREATE TABLE simple_table (the_value int)")
        run_mssql(mssql_service, "INSERT INTO simple_table VALUES (1)")
        assert run_mssql(mssql_service, "SELECT the_value FROM simple_table") == ["1"]
        run_mssql(mssql_service, "DROP TABLE simple_table")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="SQL Server container image is not supported on ARM")
def test_xdist_isolate_database(pytester: pytest.Pytester, mssql_test_helpers: str) -> None:
    """Verify mssql_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mssql"]

    {mssql_test_helpers}

    def test_1(mssql_service):
        run_mssql(mssql_service, "CREATE TABLE simple_table (the_value int)")

    def test_2(mssql_service):
        run_mssql(mssql_service, "CREATE TABLE simple_table (the_value int)")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="SQL Server container image is not supported on ARM")
def test_xdist_isolate_server(pytester: pytest.Pytester, mssql_test_helpers: str) -> None:
    """Verify mssql_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile(f"""
    import pytest

    pytest_plugins = ["pytest_databases.docker.mssql"]

    @pytest.fixture(scope="session")
    def xdist_mssql_isolation_level():
        return "server"

    {mssql_test_helpers}

    def test_1(mssql_service):
        run_mssql(mssql_service, "CREATE DATABASE db_test", database="master")

    def test_2(mssql_service):
        run_mssql(mssql_service, "CREATE DATABASE db_test", database="master")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__
