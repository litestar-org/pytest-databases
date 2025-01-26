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
    import mariadb

    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def test({service_fixture}):
        with mariadb.connect(
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

    result = pytester.runpytest("-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "connection_fixture",
    [
        "mariadb_connection",
        "mariadb_113_connection",
    ],
)
def test_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def test({connection_fixture}):
        with {connection_fixture}.cursor() as cursor:
            cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert result is not None and result[0][0] == 1
    """)

    result = pytester.runpytest("-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def test_1(mariadb_113_connection):
        with mariadb_113_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(mariadb_113_connection):
        with mariadb_113_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mariadb"]

    @pytest.fixture(scope="session")
    def xdist_mariadb_isolation_level():
        return "server"

    def test_1(mariadb_113_connection):
        with mariadb_113_connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")

    def test_2(mariadb_113_connection):
        with mariadb_113_connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")
    """)

    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)
