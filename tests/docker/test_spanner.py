from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from google.cloud import spanner

from pytest_databases.docker.spanner import spanner_responsive

if TYPE_CHECKING:
    from google.auth.credentials import Credentials

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.spanner",
]


async def test_spanner_default_config(
    spanner_port: int, spanner_instance: str, spanner_database: str, spanner_project: str
) -> None:
    assert spanner_port == 9010
    assert spanner_instance == "test-instance"
    assert spanner_database == "test-database"
    assert spanner_project == "emulator-test-project"


async def test_spanner_services(
    spanner_docker_ip: str,
    spanner_service: DockerServiceRegistry,
    spanner_port: int,
    spanner_instance: str,
    spanner_database: str,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> None:
    ping = spanner_responsive(
        spanner_docker_ip,
        spanner_port=spanner_port,
        spanner_instance=spanner_instance,
        spanner_database=spanner_database,
        spanner_project=spanner_project,
        spanner_credentials=spanner_credentials,
    )
    assert ping


async def test_spanner_service_after_start(
    spanner_startup_connection: spanner.Client,
) -> None:
    assert isinstance(spanner_startup_connection, spanner.Client)
