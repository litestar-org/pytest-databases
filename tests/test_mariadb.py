from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mariadb_service",
        "mariadb_113_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
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
