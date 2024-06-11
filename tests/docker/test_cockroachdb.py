from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.cockroachdb import cockroachdb_responsive

if TYPE_CHECKING:
    import asyncpg

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.cockroachdb",
]


def test_cockroachdb_default_config(
    cockroachdb_port: int, cockroachdb_database: str, cockroachdb_driver_opts: dict[str, str]
) -> None:
    assert cockroachdb_port == 26257
    assert cockroachdb_database == "defaultdb"
    assert cockroachdb_driver_opts == {"sslmode": "disable"}


async def test_cockroachdb_service(
    cockroachdb_docker_ip: str,
    cockroachdb_service: DockerServiceRegistry,
    cockroachdb_database: str,
    cockroachdb_port: int,
    cockroachdb_driver_opts: dict[str, str],
) -> None:
    ping = await cockroachdb_responsive(
        cockroachdb_docker_ip, cockroachdb_port, cockroachdb_database, cockroachdb_driver_opts
    )
    assert ping


async def test_cockroachdb_services_after_start(
    cockroachdb_startup_connection: asyncpg.Connection[asyncpg.Record],
) -> None:
    await cockroachdb_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
    result = await cockroachdb_startup_connection.fetchrow("select * from simple_table")
    assert bool(result is not None and result[0] == 1)
