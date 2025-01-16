from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Generator

import pytest
import redis
from redis.exceptions import ConnectionError as KeydbConnectionError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


@dataclasses.dataclass
class KeydbService(ServiceContainer):
    db: int


def keydb_responsive(service_container: ServiceContainer) -> bool:
    client = redis.Redis.from_url("redis://", host=service_container.host, port=service_container.port)
    try:
        return client.ping()
    except (ConnectionError, KeydbConnectionError):
        return False
    finally:
        client.close()


@pytest.fixture(scope="session")
def xdist_keydb_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def keydb_port(keydb_service: KeydbService) -> int:
    return keydb_service.port


@pytest.fixture(scope="session")
def keydb_host(keydb_service: KeydbService) -> str:
    return keydb_service.host


@pytest.fixture(scope="session")
def keydb_image() -> str:
    return "eqalpha/keydb"


@pytest.fixture(autouse=False, scope="session")
def keydb_service(
    docker_service: DockerService,
    xdist_keydb_isolation_level: XdistIsolationLevel,
    keydb_image: str,
) -> Generator[KeydbService, None, None]:
    worker_num = get_xdist_worker_num()
    if xdist_keydb_isolation_level == "database":
        container_num = worker_num // 1
        name = f"keydb_{container_num + 1}"
        db = worker_num
    else:
        name = f"keydb_{worker_num + 1}"
        db = 0
    with docker_service.run(
        keydb_image,
        check=keydb_responsive,
        container_port=6379,
        name=name,
        transient=xdist_keydb_isolation_level == "server",
    ) as service:
        yield KeydbService(host=service.host, port=service.port, db=db)
