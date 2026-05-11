from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "dolt_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
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
