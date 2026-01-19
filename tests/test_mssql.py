from __future__ import annotations

import pytest

from tests.conftest import PLATFORM_PROCESSOR


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mssql_service",
    ],
)
@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="ARM bug. https://github.com/pymssql/pymssql/issues/822")
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    import pymssql
    pytest_plugins = ["pytest_databases.docker.mssql"]

    def test({service_fixture}):
        conn = pymssql.connect(
            host={service_fixture}.host,
            port=str({service_fixture}.port),
            database={service_fixture}.database,
            user={service_fixture}.user,
            password={service_fixture}.password,
            timeout=2,
        )
        with conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "connection_fixture",
    [
        "mssql_connection",
    ],
)
@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="ARM bug. https://github.com/pymssql/pymssql/issues/822")
def test_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    import pymssql
    pytest_plugins = ["pytest_databases.docker.mssql"]

    def test({connection_fixture}):
        with {connection_fixture}.cursor() as cursor:
            cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert bool(result is not None and result[0][0] == 1)
            cursor.execute("drop view simple_table")

    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="ARM bug. https://github.com/pymssql/pymssql/issues/822")
def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pymssql
    pytest_plugins = ["pytest_databases.docker.mssql"]

    def test_1(mssql_connection):
        with mssql_connection.cursor() as cursor:
            cursor.execute("CREATE view simple_table as SELECT 1 as the_value;")

    def test_2(mssql_connection):
        with mssql_connection.cursor() as cursor:
            cursor.execute("CREATE view simple_table as SELECT 1 as the_value;")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


@pytest.mark.skipif(PLATFORM_PROCESSOR == "arm", reason="ARM bug. https://github.com/pymssql/pymssql/issues/822")
def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pymssql
    import pytest
    pytest_plugins = ["pytest_databases.docker.mssql"]

    @pytest.fixture(scope="session")
    def xdist_mssql_isolation_level():
        return "server"

    def test_1(mssql_service):
        with pymssql.connect(
            host=mssql_service.host,
            port=str(mssql_service.port),
            database=mssql_service.database,
            user=mssql_service.user,
            password=mssql_service.password,
            timeout=2,
            autocommit=True,
        ) as conn, conn.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")

    def test_2(mssql_service):
        with pymssql.connect(
            host=mssql_service.host,
            port=str(mssql_service.port),
            database=mssql_service.database,
            user=mssql_service.user,
            password=mssql_service.password,
            timeout=2,
            autocommit=True,
        ) as conn, conn.cursor() as cursor:
            cursor.execute("CREATE DATABASE db_test")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
