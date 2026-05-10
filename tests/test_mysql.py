from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mysql_8_service",
        "mysql_56_service",
        "mysql_57_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
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
