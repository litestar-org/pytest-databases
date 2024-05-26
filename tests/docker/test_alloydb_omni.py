from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.alloydb_omni import alloydb_omni_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.alloydb_omni",
]


async def test_alloydb_omni_default_config(
    default_alloydb_omni_service_name: str,
    alloydb_omni_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert default_alloydb_omni_service_name == "alloydb"
    assert alloydb_omni_port == 5420
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_alloydb_omni_services(
    alloydb_docker_ip: str,
    alloydb_omni_service: DockerServiceRegistry,
    alloydb_omni_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await alloydb_omni_responsive(
        alloydb_docker_ip,
        port=alloydb_omni_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping
