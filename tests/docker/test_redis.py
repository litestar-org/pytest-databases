from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.redis import redis_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.redis",
]


def test_redis_default_config(redis_port: int) -> None:
    assert redis_port == 6397


async def test_redis_service(
    redis_docker_ip: str,
    redis_service: DockerServiceRegistry,
    redis_port: int,
) -> None:
    ping = await redis_responsive(redis_docker_ip, redis_port)
    assert ping
