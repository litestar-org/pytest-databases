from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Generator

import pytest
import redis
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel
from redis.exceptions import ConnectionError as RedisConnectionError

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


@pytest.fixture(scope="session")
def xdist_dragonfly_isolate() -> XdistIsolationLevel:
    return "database"


@dataclasses.dataclass
class DragonflyService(ServiceContainer):
    db: int


def dragonfly_responsive(service_container: ServiceContainer) -> bool:
    client = redis.Redis.from_url("redis://", host=service_container.host, port=service_container.port)
    try:
        return client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        client.close()


@pytest.fixture(scope="session")
def dragonfly_port(dragonfly_service: DragonflyService) -> int:
    return dragonfly_service.port


@pytest.fixture(scope="session")
def dragonfly_host(dragonfly_service: DragonflyService) -> str:
    return dragonfly_service.host


@pytest.fixture(scope="session")
def dragonfly_image() -> str:
    return "docker.dragonflydb.io/dragonflydb/dragonfly"


@pytest.fixture(autouse=False, scope="session")
def dragonfly_service(
    docker_service: DockerService,
    dragonfly_image: str,
    xdist_dragonfly_isolate: XdistIsolationLevel,
) -> Generator[DragonflyService, None, None]:
    worker_num = get_xdist_worker_num()
    if xdist_dragonfly_isolate == "database":
        container_num = worker_num // 1
        name = f"dragonfly_{container_num + 1}"
        db = worker_num
    else:
        name = f"dragonfly_{worker_num + 1}"
        db = 0
    with docker_service.run(
        dragonfly_image,
        check=dragonfly_responsive,
        container_port=6379,
        name=name,
    ) as service:
        yield DragonflyService(host=service.host, port=service.port, db=db)
