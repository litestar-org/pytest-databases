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
    import mysql.connector
    pytest_plugins = ["pytest_databases.docker.dolt"]

    def test({service_fixture}):
        with mysql.connector.connect(
            host={service_fixture}.host,
            port={service_fixture}.port,
            user={service_fixture}.user,
            database={service_fixture}.db,
            password={service_fixture}.password,
        ) as conn, conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
        assert resp is not None and resp[0] == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import mysql.connector
    import pytest
    pytest_plugins = ["pytest_databases.docker.dolt"]

    @pytest.fixture
    def dolt_conn(dolt_service):
        with mysql.connector.connect(
            host=dolt_service.host,
            port=dolt_service.port,
            user=dolt_service.user,
            database=dolt_service.db,
            password=dolt_service.password,
        ) as conn:
            yield conn

    def test_1(dolt_conn):
        with dolt_conn.cursor() as cursor:
            cursor.execute("CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(dolt_conn):
        with dolt_conn.cursor() as cursor:
            cursor.execute("CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import mysql.connector
    import pytest
    pytest_plugins = ["pytest_databases.docker.dolt"]

    @pytest.fixture(scope="session")
    def xdist_dolt_isolation_level():
        return "server"

    @pytest.fixture
    def dolt_conn(dolt_service):
        with mysql.connector.connect(
            host=dolt_service.host,
            port=dolt_service.port,
            user=dolt_service.user,
            database=dolt_service.db,
            password=dolt_service.password,
        ) as conn:
            yield conn

    def test_1(dolt_conn):
        with dolt_conn.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")

    def test_2(dolt_conn):
        with dolt_conn.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
