"""Tests for MariaDB container service fixtures."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pytest_databases.docker.mariadb import (
    mariadb_118_service,
    mariadb_123_service,
    mariadb_130_service,
    provide_mariadb_service,
)
from pytest_databases.types import ServiceContainer


def test_mariadb_performance_schema_and_version_fixtures() -> None:
    """Verify provide_mariadb_service enables performance_schema and version fixtures exist."""
    assert callable(mariadb_118_service)
    assert callable(mariadb_123_service)
    assert callable(mariadb_130_service)

    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=33306,
        container=mock_container,
    )

    with provide_mariadb_service(
        docker_service=mock_docker,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level="database",
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.port == 33306

    assert mock_docker.run.call_args.kwargs["command"] == "--performance-schema=ON"


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mariadb_service",
        "mariadb_113_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify mariadb_service starts and executes SQL queries."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def run_mariadb(service, sql):
        result = service.container.exec_run([
            "mariadb",
            f"--user={{service.user}}",
            f"--password={{service.password}}",
            "-D",
            service.db,
            "--batch",
            "--skip-column-names",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().strip()

    def test({service_fixture}):
        assert run_mariadb({service_fixture}, "select 1 as is_available") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify mariadb_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def run_mariadb(service, sql):
        result = service.container.exec_run([
            "mariadb",
            f"--user={service.user}",
            f"--password={service.password}",
            "-D",
            service.db,
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify mariadb_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    @pytest.fixture(scope="session")
    def xdist_mariadb_isolation_level():
        return "server"

    def run_mariadb(service, sql):
        result = service.container.exec_run([
            "mariadb",
            f"--user={service.user}",
            f"--password={service.password}",
            "-D",
            service.db,
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE DATABASE db_test")

    def test_2(mariadb_113_service):
        run_mariadb(mariadb_113_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
