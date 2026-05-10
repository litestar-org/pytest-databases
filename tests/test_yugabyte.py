from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import shlex

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
    pytester.makepyfile("""
    import pytest
    import shlex

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
    pytester.makepyfile("""
    import pytest
    import shlex

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
