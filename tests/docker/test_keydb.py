from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.keydb import keydb_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.keydb",
]


def test_keydb_default_config(keydb_port: int) -> None:
    assert keydb_port == 6396


async def test_keydb_service(
    keydb_docker_ip: str,
    keydb_service: DockerServiceRegistry,
    keydb_port: int,
) -> None:
    ping = await keydb_responsive(keydb_docker_ip, keydb_port)
    assert ping
