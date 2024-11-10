from __future__ import annotations

import oracledb

from pytest_databases.docker.oracle import OracleService

pytest_plugins = [
    "pytest_databases.docker.oracle",
]


def test_oracle18c_service(oracle18c_service: OracleService) -> None:
    conn = oracledb.connect(
        user=oracle18c_service.user,
        password=oracle18c_service.password,
        dsn=f"{oracle18c_service.host}:{oracle18c_service.port!s}/{oracle18c_service.service_name}",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 'Hello World!' FROM dual")
        res = cur.fetchall()[0][0]
        assert "Hello World!" in res


def test_oracle23ai_service(oracle23ai_service: OracleService) -> None:
    conn = oracledb.connect(
        user=oracle23ai_service.user,
        password=oracle23ai_service.password,
        dsn=f"{oracle23ai_service.host}:{oracle23ai_service.port!s}/{oracle23ai_service.service_name}",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 'Hello World!' FROM dual")
        res = cur.fetchall()[0][0]
        assert "Hello World!" in res


def test_oracle_services_after_start(
    oracle_startup_connection: oracledb.Connection,
) -> None:
    with oracle_startup_connection.cursor() as cursor:
        cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_oracle18c_services_after_start(
    oracle18c_startup_connection: oracledb.Connection,
) -> None:
    with oracle18c_startup_connection.cursor() as cursor:
        cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_oracle23ai_services_after_start(
    oracle23ai_startup_connection: oracledb.Connection,
) -> None:
    with oracle23ai_startup_connection.cursor() as cursor:
        cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
