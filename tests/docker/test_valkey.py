from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.valkey import valkey_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.valkey",
]


def test_valkey_default_config(valkey_port: int) -> None:
    assert valkey_port == 6308


async def test_valkey_service(
    valkey_docker_ip: str,
    valkey_service: DockerServiceRegistry,
    valkey_port: int,
) -> None:
    ping = await valkey_responsive(valkey_docker_ip, valkey_port)
    assert ping
