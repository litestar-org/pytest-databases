from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Generator

import pytest
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


@dataclasses.dataclass
class RedisService(ServiceContainer):
    db: int


def redis_responsive(service_container: ServiceContainer) -> bool:
    client = Redis(host=service_container.host, port=service_container.port)
    try:
        return client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        client.close()


@pytest.fixture(scope="session")
def redis_port(redis_service: RedisService) -> int:
    return redis_service.port


@pytest.fixture(scope="session")
def redis_host(redis_service: RedisService) -> str:
    return redis_service.host


@pytest.fixture(scope="session")
def reuse_redis() -> bool:
    return True


@pytest.fixture(scope="session")
def redis_image() -> str:
    return "redis:latest"


@pytest.fixture(autouse=False, scope="session")
def redis_service(
    docker_service: DockerService,
    reuse_redis: bool,
    redis_image: str,
) -> Generator[RedisService, None, None]:
    worker_num = get_xdist_worker_num()
    if reuse_redis:
        container_num = worker_num // 1
        name = f"redis_{container_num + 1}"
        db = worker_num
    else:
        name = f"redis_{worker_num + 1}"
        db = 0
    with docker_service.run(
        redis_image,
        check=redis_responsive,
        container_port=6379,
        name=name,
    ) as service:
        yield RedisService(host=service.host, port=service.port, db=db)
