"""Tests for MySQL container service fixtures."""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import mysql as mysql_mod
from pytest_databases.docker.mysql import provide_mysql_service
from pytest_databases.types import ServiceContainer
from tests.conftest import assert_legacy_platform_handling, unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator


def test_mysql_performance_schema_and_native_platform() -> None:
    """Verify provide_mysql_service enables performance_schema and forwards a native (None) platform."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=33306,
        container=mock_container,
    )

    with provide_mysql_service(
        docker_service=mock_docker,
        image="mysql:9.7",
        name="mysql-9.7",
        isolation_level="database",
        platform=None,
        user="app",
        password="secret",
        root_password="secret",
        database="db",
    ) as service:
        assert service.port == 33306

    assert mock_docker.run.call_args.kwargs["command"] == "--performance-schema=ON"
    assert mock_docker.run.call_args.kwargs["platform"] is None


def _user_platform() -> str:
    return "linux/arm64"


@pytest.mark.parametrize(
    ("platform_func", "expected_platform", "expected_warnings"),
    [
        (_user_platform, "linux/arm64", 1),
        (mysql_mod.platform, None, 0),
    ],
)
def test_mysql_8_services_honor_legacy_platform_override(
    monkeypatch: pytest.MonkeyPatch,
    platform_func: object,
    expected_platform: str | None,
    expected_warnings: int,
) -> None:
    """Verify MySQL 8+ services run natively unless a user-defined ``platform`` override is visible."""
    captured: dict[str, object] = {}

    @contextmanager
    def fake_provide(**kwargs: object) -> Generator[str, None, None]:
        captured.update(kwargs)
        yield "service"

    monkeypatch.setattr(mysql_mod, "provide_mysql_service", fake_provide)
    request = MagicMock()
    request._fixturemanager.getfixturedefs.return_value = [SimpleNamespace(func=platform_func)]
    request.getfixturevalue.return_value = "linux/arm64"

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fixture_gen = unwrap_fixture(mysql_mod.mysql_8_service)(
            request, MagicMock(), "database", "app", "pw", "pw", "db"
        )
        assert next(fixture_gen) == "service"

    deprecations = [w for w in record if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == expected_warnings
    if expected_warnings:
        assert "multi-arch" in str(deprecations[0].message)
    assert captured["platform"] == expected_platform


@pytest.mark.parametrize("mode", ["default", "override", "legacy"])
def test_mysql_platform_and_legacy_platform_fixture(pytester: pytest.Pytester, mode: str) -> None:
    """Verify mysql_platform defaults to x86_64, honors a legacy platform override, and the bare shim warns once."""
    assert_legacy_platform_handling(pytester, "pytest_databases.docker.mysql", "mysql_platform", "linux/x86_64", mode)


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mysql_8_service",
        "mysql_56_service",
        "mysql_57_service",
        "mysql_97_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify mysql_service starts and executes SQL queries."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mysql"]

    def run_mysql(service, sql):
        result = service.container.exec_run(
            [
                "mysql",
                f"--user={{service.user}}",
                "-D",
                service.db,
                "--batch",
                "--skip-column-names",
                "-e",
                sql,
            ],
            environment={{"MYSQL_PWD": service.password}},
        )
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().strip()

    def test({service_fixture}):
        assert run_mysql({service_fixture}, "select 1 as is_available") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify mysql_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mysql"]

    def run_mysql(service, sql):
        result = service.container.exec_run(
            [
                "mysql",
                f"--user={service.user}",
                "-D",
                service.db,
                "-e",
                sql,
            ],
            environment={"MYSQL_PWD": service.password},
        )
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify mysql_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mysql"]

    @pytest.fixture(scope="session")
    def xdist_mysql_isolation_level():
        return "server"

    def run_mysql(service, sql):
        result = service.container.exec_run(
            [
                "mysql",
                f"--user={service.user}",
                "-D",
                service.db,
                "-e",
                sql,
            ],
            environment={"MYSQL_PWD": service.password},
        )
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_1(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE DATABASE db_test")

    def test_2(mysql_56_service):
        run_mysql(mysql_56_service, "CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
