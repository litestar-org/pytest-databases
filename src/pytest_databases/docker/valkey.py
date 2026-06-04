from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _exec_valkey_cli(container: Container, *args: str, db: int = 0) -> tuple[int, bytes]:
    result = container.exec_run([
        "valkey-cli",
        "-h",
        "localhost",
        "-p",
        "6379",
        "-n",
        str(db),
        *args,
    ])
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


@dataclasses.dataclass
class ValkeyService(ServiceContainer):
    db: int


@pytest.fixture(scope="session")
def xdist_valkey_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(autouse=False, scope="session")
def valkey_port(valkey_service: ValkeyService) -> int:
    return valkey_service.port


@pytest.fixture(autouse=False, scope="session")
def valkey_host(valkey_service: ValkeyService) -> str:
    return valkey_service.host


@pytest.fixture(autouse=False, scope="session")
def valkey_image() -> str:
    return "valkey/valkey:latest"


@pytest.fixture(autouse=False, scope="session")
def valkey_service(
    docker_service: DockerService,
    valkey_image: str,
    xdist_valkey_isolation_level: XdistIsolationLevel,
) -> Generator[ValkeyService, None, None]:
    worker_num = get_xdist_worker_num()
    name = "valkey"
    db = 0
    if worker_num is not None:
        if xdist_valkey_isolation_level == "database":
            container_num = worker_num // 1
            name += f"_{container_num + 1}"
            db = worker_num
        else:
            name += f"_{worker_num + 1}"

    def _responsive(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_valkey_cli(_service.container, "PING")
        return exit_code == 0 and output.strip().endswith(b"PONG")

    with docker_service.run(
        valkey_image,
        check=_responsive,
        container_port=6379,
        name=name,
        transient=xdist_valkey_isolation_level == "server",
    ) as service:
        yield ValkeyService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db,
        )
