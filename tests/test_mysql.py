from __future__ import annotations

import pytest

from tests.conftest import PLATFORM_PROCESSOR


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mysql_8_service",
        pytest.param("mysql_56_service", marks=pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="No ARM container")),
        pytest.param("mysql_57_service", marks=pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="No ARM container")),
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    import mysql.connector
    pytest_plugins = ["pytest_databases.docker.mysql"]

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

    result = pytester.runpytest("-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "connection_fixture",
    [
        pytest.param("mysql_56_connection", marks=pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="No ARM container")),
        pytest.param("mysql_57_connection", marks=pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="No ARM container")),
    ],
)
def test_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mysql"]

    def test({connection_fixture}):
        with {connection_fixture}.cursor() as cursor:
            cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert result is not None and result[0][0] == 1
    """)

    result = pytester.runpytest("-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="No ARM container. Can this be changed to mysql8?")
def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mysql"]

    def test_1(mysql_56_connection):
        with mysql_56_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE simple_table as SELECT 1 as the_value;")

    def test_2(mysql_56_connection):
        with mysql_56_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="No ARM container. Can this be changed to mysql8?")
def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mysql"]

    @pytest.fixture(scope="session")
    def xdist_mysql_isolation_level():
        return "server"

    def test_1(mysql_56_connection):
        with mysql_56_connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")

    def test_2(mysql_56_connection):
        with mysql_56_connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")
    """)

    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)
