from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Generator, Literal

import pytest
import redis
from redis.exceptions import ConnectionError as valkeyConnectionError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


@pytest.fixture(scope="session")
def xdist_valkey_isolate() -> Literal["database", "server"]:
    return "database"


@dataclasses.dataclass
class ValkeyService(ServiceContainer):
    db: int


def valkey_responsive(service_container: ServiceContainer) -> bool:
    client = redis.Redis.from_url("redis://", host=service_container.host, port=service_container.port)
    try:
        return client.ping()
    except (ConnectionError, valkeyConnectionError):
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
    xdist_valkey_isolate: Literal["database", "server"],
) -> Generator[ValkeyService, None, None]:
    worker_num = get_xdist_worker_num()
    if xdist_valkey_isolate == "database":
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
