from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "oracle_18c_service",
        "oracle_23ai_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    import oracledb
    pytest_plugins = ["pytest_databases.docker.oracle"]

    def test({service_fixture}):
        conn = oracledb.connect(
            user={service_fixture}.user,
            password={service_fixture}.password,
            service_name={service_fixture}.service_name,
            host={service_fixture}.host,
            port={service_fixture}.port,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM dual")
            res = cur.fetchone()[0]
            assert res == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("connection_fixture", ["oracle_18c_connection", "oracle_23ai_connection"])
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

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)
