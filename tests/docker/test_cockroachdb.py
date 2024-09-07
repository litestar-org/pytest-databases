from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_databases.docker.cockroachdb import cockroachdb_responsive

if TYPE_CHECKING:
    import psycopg

    from pytest_databases.docker import DockerServiceRegistry

pytest_plugins = [
    "pytest_databases.docker.cockroachdb",
]


def test_cockroachdb_default_config(
    cockroachdb_port: int, cockroachdb_database: str, cockroachdb_driver_opts: dict[str, str]
) -> None:
    assert cockroachdb_port == 26257
    assert cockroachdb_database == "defaultdb"
    assert cockroachdb_driver_opts == {"sslmode": "disable"}


def test_cockroachdb_service(
    cockroachdb_docker_ip: str,
    cockroachdb_service: DockerServiceRegistry,
    cockroachdb_database: str,
    cockroachdb_port: int,
    cockroachdb_driver_opts: dict[str, str],
) -> None:
    ping = cockroachdb_responsive(
        cockroachdb_docker_ip, cockroachdb_port, cockroachdb_database, cockroachdb_driver_opts
    )
    assert ping


def test_cockroachdb_services_after_start(
    cockroachdb_startup_connection: psycopg.Connection,
) -> None:
    cockroachdb_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
    result = cockroachdb_startup_connection.execute("select * from simple_table").fetchone()
    assert bool(result is not None and result[0] == 1)
