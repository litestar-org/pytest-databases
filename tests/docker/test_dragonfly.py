from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_databases.docker.redis import redis_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytest_plugins = [
    "pytest_databases.docker.dragonfly",
]


def test_dragonfly_default_config(dragonfly_port: int) -> None:
    assert dragonfly_port == 6398


def test_dragonfly_service(
    dragonfly_docker_ip: str,
    dragonfly_service: DockerServiceRegistry,
    dragonfly_port: int,
) -> None:
    ping = redis_responsive(dragonfly_docker_ip, dragonfly_port)
    assert ping
