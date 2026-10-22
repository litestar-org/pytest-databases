"""Tests for YugabyteDB distributed SQL service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from pytest_databases.docker.yugabyte import (
    YUGABYTE_DATABASE,
    YUGABYTE_PASSWORD,
    YUGABYTE_USER,
    provide_yugabyte_service,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    import pytest


def test_provide_yugabyte_service_validates_without_sidecar_containers() -> None:
    """Verify provide_yugabyte_service uses service.container directly without spawning sidecar containers."""
    docker_service = MagicMock()
    dummy_container = MagicMock()
    dummy_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        check = kwargs["check"]
        assert callable(check)
        service_container = ServiceContainer(host="127.0.0.1", port=5433, container=dummy_container)
        assert check(service_container) is True
        yield service_container

    docker_service.run.side_effect = fake_run

    with (
        patch("pytest_databases.docker.yugabyte.socket.create_connection") as mock_connect,
        provide_yugabyte_service(
            docker_service,
            isolation_level="database",
            image="software.yugabyte.com/yugabytedb/yugabyte:latest",
            user=YUGABYTE_USER,
            password=YUGABYTE_PASSWORD,
            database=YUGABYTE_DATABASE,
        ) as service,
    ):
        assert service.host == "127.0.0.1"
        assert service.port == 5433
        assert service.database == YUGABYTE_DATABASE
        assert service.user == YUGABYTE_USER
        assert service.password == YUGABYTE_PASSWORD
        mock_connect.assert_called_once_with(("127.0.0.1", 5433), timeout=2.0)
        docker_service._client.containers.run.assert_not_called()


def test_service_fixture(pytester: pytest.Pytester) -> None:
    """Verify yugabyte_service provisions custom credentials and executes SQL."""
    pytester.makepyfile("""
    import shlex
    import pytest

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def yugabyte_user():
        return "custom_yugabyte_user"

    @pytest.fixture(scope="session")
    def yugabyte_password():
        return "custom-yugabyte-password"

    @pytest.fixture(scope="session")
    def yugabyte_database():
        return "custom_yugabyte_database"

    def run_ysqlsh(yugabyte_service, sql, database=None):
        database = database or yugabyte_service.database
        command = " ".join([
            "bin/ysqlsh",
            "-h $(hostname)",
            f"-U {shlex.quote(yugabyte_service.user)}",
            f"-d {shlex.quote(database)}",
            "-tAc",
            shlex.quote(sql),
        ])
        result = yugabyte_service.container.exec_run(["sh", "-c", command])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return result.output.decode().strip()

    def test(yugabyte_service) -> None:
        assert yugabyte_service.user == "custom_yugabyte_user"
        assert yugabyte_service.password == "custom-yugabyte-password"
        assert yugabyte_service.database == "custom_yugabyte_database"
        assert run_ysqlsh(yugabyte_service, "SELECT 1") == "1"
        run_ysqlsh(yugabyte_service, "CREATE TABLE IF NOT EXISTS simple_table AS SELECT 1")
        assert run_ysqlsh(yugabyte_service, "SELECT * FROM simple_table") == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify database-isolated yugabyte_service isolates xdist workers in separate databases."""
    pytester.makepyfile("""
    import shlex
    import pytest

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    def run_ysqlsh(yugabyte_service, sql):
        command = " ".join([
            "bin/ysqlsh",
            "-h $(hostname)",
            f"-U {shlex.quote(yugabyte_service.user)}",
            f"-d {shlex.quote(yugabyte_service.database)}",
            "-c",
            shlex.quote(sql),
        ])
        result = yugabyte_service.container.exec_run(["sh", "-c", command])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_one(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE TABLE foo AS SELECT 1")

    def test_two(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE TABLE foo AS SELECT 1")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify server-isolated yugabyte_service starts separate containers per xdist worker."""
    pytester.makepyfile("""
    import shlex
    import pytest

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def xdist_yugabyte_isolation_level():
        return "server"

    def run_ysqlsh(yugabyte_service, sql, database="yugabyte"):
        command = " ".join([
            "bin/ysqlsh",
            "-h $(hostname)",
            f"-U {shlex.quote(yugabyte_service.user)}",
            f"-d {shlex.quote(database)}",
            "-c",
            shlex.quote(sql),
        ])
        result = yugabyte_service.container.exec_run(["sh", "-c", command])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_one(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE DATABASE foo")

    def test_two(yugabyte_service) -> None:
        run_ysqlsh(yugabyte_service, "CREATE DATABASE foo")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)
