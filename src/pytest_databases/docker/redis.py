from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclasses.dataclass
class RedisService(ServiceContainer):
    db: int


@pytest.fixture(scope="session")
def xdist_redis_isolation_level() -> XdistIsolationLevel:
    return "database"


def redis_responsive(service_container: ServiceContainer) -> bool:
    client = Redis(host=service_container.host, port=service_container.port)
    try:
        return client.ping()
    except (ConnectionError, RedisConnectionError):
        return False
    finally:
        client.close()


@pytest.fixture(autouse=False, scope="session")
def redis_port(redis_service: RedisService) -> int:
    return redis_service.port


@pytest.fixture(autouse=False, scope="session")
def redis_host(redis_service: RedisService) -> str:
    return redis_service.host


@pytest.fixture(autouse=False, scope="session")
def redis_image() -> str:
    return "redis:latest"


@pytest.fixture(autouse=False, scope="session")
def redis_service(
    docker_service: DockerService,
    redis_image: str,
    xdist_redis_isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    worker_num = get_xdist_worker_num()
    name = "redis"
    db = 0
    if worker_num is not None:
        if xdist_redis_isolation_level == "database":
            db = worker_num
        else:
            name += f"_{worker_num + 1}"

    with docker_service.run(
        redis_image,
        check=redis_responsive,
        container_port=6379,
        name=name,
        transient=xdist_redis_isolation_level == "server",
    ) as service:
        yield RedisService(host=service.host, port=service.port, db=db)


@pytest.fixture(autouse=False, scope="session")
def dragonfly_image() -> str:
    return "docker.dragonflydb.io/dragonflydb/dragonfly"


@pytest.fixture(autouse=False, scope="session")
def dragonfly_service(
    docker_service: DockerService,
    dragonfly_image: str,
    xdist_redis_isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    worker_num = get_xdist_worker_num()
    name = "dragonfly"
    db = 0
    if worker_num is not None:
        if xdist_redis_isolation_level == "database":
            db = worker_num
        else:
            name += f"_{worker_num + 1}"

    with docker_service.run(
        dragonfly_image,
        check=redis_responsive,
        container_port=6379,
        name=name,
        transient=xdist_redis_isolation_level == "server",
    ) as service:
        yield RedisService(host=service.host, port=service.port, db=db)


@pytest.fixture(autouse=False, scope="session")
def dragonfly_port(dragonfly_service: RedisService) -> int:
    return dragonfly_service.port


@pytest.fixture(autouse=False, scope="session")
def dragonfly_host(dragonfly_service: RedisService) -> str:
    return dragonfly_service.host


@pytest.fixture(autouse=False, scope="session")
def keydb_image() -> str:
    return "eqalpha/keydb"


@pytest.fixture(autouse=False, scope="session")
def keydb_service(
    docker_service: DockerService,
    keydb_image: str,
    xdist_redis_isolation_level: XdistIsolationLevel,
) -> Generator[RedisService, None, None]:
    worker_num = get_xdist_worker_num()
    name = "keydb"
    db = 0
    if worker_num is not None:
        if xdist_redis_isolation_level == "database":
            db = worker_num
        else:
            name += f"_{worker_num + 1}"

    with docker_service.run(
        keydb_image,
        check=redis_responsive,
        container_port=6379,
        name=name,
        transient=xdist_redis_isolation_level == "server",
    ) as service:
        yield RedisService(host=service.host, port=service.port, db=db)


@pytest.fixture(autouse=False, scope="session")
def keydb_port(keydb_service: RedisService) -> int:
    return keydb_service.port


@pytest.fixture(autouse=False, scope="session")
def keydb_host(keydb_service: RedisService) -> str:
    return keydb_service.host
