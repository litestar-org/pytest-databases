from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Generator

import pytest
import redis

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


@dataclasses.dataclass
class ValkeyService(ServiceContainer):
    db: int


@pytest.fixture(scope="session")
def xdist_valkey_isolation_level() -> XdistIsolationLevel:
    return "database"


def valkey_responsive(service_container: ServiceContainer) -> bool:
    client = redis.Redis.from_url("redis://", host=service_container.host, port=service_container.port)
    try:
        return client.ping()
    except redis.exceptions.ConnectionError:
        return False
    finally:
        client.close()


@pytest.fixture(scope="session")
def valkey_port(valkey_service: ValkeyService) -> int:
    return valkey_service.port


@pytest.fixture(scope="session")
def valkey_host(valkey_service: ValkeyService) -> str:
    return valkey_service.host


@pytest.fixture(scope="session")
def valkey_image() -> str:
    return "valkey/valkey:latest"


@pytest.fixture(autouse=False, scope="session")
def valkey_service(
    docker_service: DockerService,
    valkey_image: str,
    xdist_valkey_isolation_level: XdistIsolationLevel,
) -> Generator[ValkeyService, None, None]:
    worker_num = get_xdist_worker_num()
    if xdist_valkey_isolation_level == "database":
        container_num = worker_num // 1
        name = f"valkey_{container_num + 1}"
        db = worker_num
    else:
        name = f"valkey_{worker_num + 1}"
        db = 0
    with docker_service.run(
        valkey_image,
        check=valkey_responsive,
        container_port=6379,
        name=name,
    ) as service:
        yield ValkeyService(host=service.host, port=service.port, db=db)
