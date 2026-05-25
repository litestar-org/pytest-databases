from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest
from docker.errors import ContainerError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService


REDIS_PROBE_IMAGE = "redis:latest"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _exec_redis_cli(container: Container, *args: str, db: int = 0) -> tuple[int, bytes]:
    result = container.exec_run([
        "redis-cli",
        "-h",
        "localhost",
        "-p",
        "6379",
        "-n",
        str(db),
        *args,
    ])
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _probe_redis_endpoint(
    docker_service: DockerService,
    service: ServiceContainer,
    *args: str,
    db: int = 0,
    probe_image: str = REDIS_PROBE_IMAGE,
) -> tuple[int, bytes]:
    try:
        output = docker_service._client.containers.run(
            image=probe_image,
            command=[
                "redis-cli",
                "-h",
                service.host,
                "-p",
                str(service.port),
                "-n",
                str(db),
                *args,
            ],
            network_mode="host",
            remove=True,
        )
    except ContainerError as exc:
        return exc.exit_status, _output_to_bytes(exc.stderr) if exc.stderr else str(exc).encode()
    return 0, _output_to_bytes(output)


@dataclasses.dataclass
class RedisService(ServiceContainer):
    db: int


@pytest.fixture(scope="session")
def xdist_redis_isolation_level() -> XdistIsolationLevel:
    return "database"


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

    def _responsive(_service: ServiceContainer) -> bool:
        exit_code, output = _probe_redis_endpoint(docker_service, _service, "PING")
        return exit_code == 0 and output.strip().endswith(b"PONG")

    with docker_service.run(
        redis_image,
        check=_responsive,
        container_port=6379,
        name=name,
        transient=xdist_redis_isolation_level == "server",
    ) as service:
        yield RedisService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db,
        )


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

    def _responsive(_service: ServiceContainer) -> bool:
        exit_code, output = _probe_redis_endpoint(docker_service, _service, "PING")
        return exit_code == 0 and output.strip().endswith(b"PONG")

    with docker_service.run(
        dragonfly_image,
        check=_responsive,
        container_port=6379,
        name=name,
        transient=xdist_redis_isolation_level == "server",
    ) as service:
        yield RedisService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db,
        )


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

    def _responsive(_service: ServiceContainer) -> bool:
        exit_code, output = _probe_redis_endpoint(docker_service, _service, "PING")
        return exit_code == 0 and output.strip().endswith(b"PONG")

    with docker_service.run(
        keydb_image,
        check=_responsive,
        container_port=6379,
        name=name,
        transient=xdist_redis_isolation_level == "server",
    ) as service:
        yield RedisService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db,
        )


@pytest.fixture(autouse=False, scope="session")
def keydb_port(keydb_service: RedisService) -> int:
    return keydb_service.port


@pytest.fixture(autouse=False, scope="session")
def keydb_host(keydb_service: RedisService) -> str:
    return keydb_service.host
