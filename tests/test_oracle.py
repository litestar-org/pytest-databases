from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip()


@pytest.mark.parametrize(
    "service_fixture",
    [
        "oracle_18c_service",
        "oracle_23ai_service",
        "oracle_23ai_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    import oracledb
    pytest_plugins = ["pytest_databases.docker.oracle"]

    def test({service_fixture}):
        conn = oracledb.connect(
            user=service_fixture.user,
            password=service_fixture.password,
            dsn=f"{{{service_fixture}.host}}:{{{service_fixture}.port!s}}/{{{service_fixture}.service_name}}",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 'Hello World!' FROM dual")
            res = cur.fetchall()[0][0]
            assert "Hello World!" in res
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("connection_fixture", ["oracle_18c_connection"])
def test_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    import oracledb
    pytest_plugins = ["pytest_databases.docker.oracle"]

    def test({connection_fixture}):
        with {connection_fixture}.cursor() as cursor:
            cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert bool(result is not None and result[0][0] == 1)
    """)
