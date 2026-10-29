"""Tests for Dolt SQL container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker.dolt import dolt_platform, platform, provide_dolt_service
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Callable


def test_dolt_default_platform_is_native() -> None:
    """Verify Dolt defaults to native multi-arch platform (None) rather than forcing linux/x86_64."""
    assert _unwrap_fixture(dolt_platform)() is None
    assert _unwrap_fixture(platform)(None) is None

    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=33306,
        container=mock_container,
    )

    with provide_dolt_service(
        docker_service=mock_docker,
        image="dolthub/dolt-sql-server:latest",
        name="dolt",
        isolation_level="database",
        platform=None,
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.port == 33306

    assert mock_docker.run.call_args.kwargs["platform"] is None


@pytest.mark.parametrize(
    "service_fixture",
    [
        "dolt_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify dolt_service starts and executes SQL queries."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.dolt"]

    def run_dolt(service, sql):
        result = service.container.exec_run([
            "dolt",
            "--use-db",
            service.db,
            "sql",
            "-q",
            sql,
            "-r",
            "csv",
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().splitlines()[-1].strip()

    def test({service_fixture}):
        assert run_dolt({service_fixture}, "select 1 as is_available") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify dolt_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.dolt"]

    def run_dolt(service, sql):
        result = service.container.exec_run([
            "dolt",
            "--use-db",
            service.db,
            "sql",
            "-q",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(dolt_service):
        run_dolt(dolt_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(dolt_service):
        run_dolt(dolt_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify dolt_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.dolt"]

    @pytest.fixture(scope="session")
    def xdist_dolt_isolation_level():
        return "server"

    def run_dolt(service, sql):
        result = service.container.exec_run([
            "dolt",
            "--use-db",
            service.db,
            "sql",
            "-q",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(dolt_service):
        run_dolt(dolt_service, "CREATE DATABASE db_test")

    def test_2(dolt_service):
        run_dolt(dolt_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__
