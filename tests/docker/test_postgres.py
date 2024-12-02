from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg

from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701

if TYPE_CHECKING:
    from pytest_databases.docker.postgres import PostgresService


pytest_plugins = [
    "pytest_databases.docker.postgres",
]


def postgres_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    with psycopg.connect(
        _make_connection_string(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )
    ) as conn:
        db_open = conn.execute("SELECT 1").fetchone()
        return bool(db_open is not None and db_open[0] == 1)


def test_postgres_service(postgres_service: PostgresService) -> None:
    ping = postgres_responsive(
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
        user=postgres_service.user,
        password=postgres_service.password,
    )
    assert ping


def test_postgres_12_service(
    postgres_12_service: PostgresService,
) -> None:
    ping = postgres_responsive(
        host=postgres_12_service.host,
        port=postgres_12_service.port,
        database=postgres_12_service.database,
        user=postgres_12_service.user,
        password=postgres_12_service.password,
    )
    assert ping


def test_postgres_13_service(
    postgres_13_service: PostgresService,
) -> None:
    ping = postgres_responsive(
        host=postgres_13_service.host,
        port=postgres_13_service.port,
        database=postgres_13_service.database,
        user=postgres_13_service.user,
        password=postgres_13_service.password,
    )
    assert ping


def test_postgres_14_service(
    postgres_14_service: PostgresService,
) -> None:
    ping = postgres_responsive(
        host=postgres_14_service.host,
        port=postgres_14_service.port,
        database=postgres_14_service.database,
        user=postgres_14_service.user,
        password=postgres_14_service.password,
    )
    assert ping


def test_postgres_15_service(
    postgres_15_service: PostgresService,
) -> None:
    ping = postgres_responsive(
        host=postgres_15_service.host,
        port=postgres_15_service.port,
        database=postgres_15_service.database,
        user=postgres_15_service.user,
        password=postgres_15_service.password,
    )
    assert ping


def test_postgres_16_service(
    postgres_16_service: PostgresService,
) -> None:
    ping = postgres_responsive(
        host=postgres_16_service.host,
        port=postgres_16_service.port,
        database=postgres_16_service.database,
        user=postgres_16_service.user,
        password=postgres_16_service.password,
    )
    assert ping


def test_postgres_17_service(
    postgres_17_service: PostgresService,
) -> None:
    ping = postgres_responsive(
        host=postgres_17_service.host,
        port=postgres_17_service.port,
        database=postgres_17_service.database,
        user=postgres_17_service.user,
        password=postgres_17_service.password,
    )
    assert ping


def test_postgres_17_service_after_start(
    postgres17_startup_connection: psycopg.Connection,
) -> None:
    postgres17_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres17_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_16_service_after_start(
    postgres16_startup_connection: psycopg.Connection,
) -> None:
    postgres16_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres16_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_15_service_after_start(
    postgres15_startup_connection: psycopg.Connection,
) -> None:
    postgres15_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres15_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_14_service_after_start(
    postgres14_startup_connection: psycopg.Connection,
) -> None:
    postgres14_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres14_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_13_service_after_start(
    postgres13_startup_connection: psycopg.Connection,
) -> None:
    postgres13_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres13_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_12_service_after_start(
    postgres12_startup_connection: psycopg.Connection,
) -> None:
    postgres12_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres12_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)
