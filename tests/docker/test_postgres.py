from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_databases.docker.postgres import postgres_responsive

if TYPE_CHECKING:
    import psycopg

    from pytest_databases.docker import DockerServiceRegistry

pytest_plugins = [
    "pytest_databases.docker.postgres",
]


def test_postgres_default_config(
    default_postgres_service_name: str,
    postgres_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert default_postgres_service_name == "postgres17"
    assert postgres_port == 5428
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


def test_postgres_12_config(
    postgres12_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres12_port == 5423
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


def test_postgres_13_config(
    postgres13_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres13_port == 5424
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


def test_postgres_14_config(
    postgres14_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres14_port == 5425
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


def test_postgres_15_config(
    postgres15_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres15_port == 5426
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


def test_postgres_16_config(
    postgres16_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres16_port == 5427
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"

def test_postgres_17_config(
    postgres17_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres17_port == 5428
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"

def test_postgres_services(
    postgres_docker_ip: str,
    postgres_service: DockerServiceRegistry,
    postgres_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


def test_postgres_12_services(
    postgres_docker_ip: str,
    postgres12_service: DockerServiceRegistry,
    postgres12_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres12_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


def test_postgres_13_services(
    postgres_docker_ip: str,
    postgres13_service: DockerServiceRegistry,
    postgres13_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres13_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


def test_postgres_14_services(
    postgres_docker_ip: str,
    postgres14_service: DockerServiceRegistry,
    postgres14_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres14_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


def test_postgres_15_services(
    postgres_docker_ip: str,
    postgres15_service: DockerServiceRegistry,
    postgres15_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres15_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


def test_postgres_16_services(
    postgres_docker_ip: str,
    postgres16_service: DockerServiceRegistry,
    postgres16_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres16_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping

def test_postgres_17_services(
    postgres_docker_ip: str,
    postgres17_service: DockerServiceRegistry,
    postgres17_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = postgres_responsive(
        postgres_docker_ip,
        port=postgres17_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping

def test_postgres_17_services_after_start(
    postgres17_startup_connection: psycopg.Connection,
) -> None:
    postgres17_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres17_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)

def test_postgres_16_services_after_start(
    postgres16_startup_connection: psycopg.Connection,
) -> None:
    postgres16_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres16_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_15_services_after_start(
    postgres15_startup_connection: psycopg.Connection,
) -> None:
    postgres15_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres15_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_14_services_after_start(
    postgres14_startup_connection: psycopg.Connection,
) -> None:
    postgres14_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres14_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_13_services_after_start(
    postgres13_startup_connection: psycopg.Connection,
) -> None:
    postgres13_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres13_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)


def test_postgres_12_services_after_start(
    postgres12_startup_connection: psycopg.Connection,
) -> None:
    postgres12_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
    result = postgres12_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)
