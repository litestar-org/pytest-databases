from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.cockroachdb import cockroachdb_responsive

if TYPE_CHECKING:
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
