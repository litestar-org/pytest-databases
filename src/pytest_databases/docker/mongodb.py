from __future__ import annotations

import contextlib
from collections.abc import Generator
from dataclasses import dataclass
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


def _exec_mongosh(
    container: Container,
    eval_script: str,
    *,
    user: str,
    password: str,
    database: str | None = None,
) -> tuple[int, bytes]:
    cmd = [
        "mongosh",
        "--quiet",
        "--host",
        "localhost",
        "--port",
        "27017",
        "-u",
        user,
        "-p",
        password,
        "--authenticationDatabase",
        "admin",
    ]
    if database is not None:
        cmd.append(database)
    cmd.extend(["--eval", eval_script])
    result = container.exec_run(cmd)
    exit_code = result.exit_code if result.exit_code is not None else -1
    return exit_code, _output_to_bytes(result.output)


@dataclass
class MongoDBService(ServiceContainer):
    username: str
    password: str
    database: str


@pytest.fixture(scope="session")
def xdist_mongodb_isolation_level() -> XdistIsolationLevel:
    return "database"


@contextlib.contextmanager
def _provide_mongodb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[MongoDBService, None, None]:
    username = "mongo_user"
    password = "mongo_password"
    default_database_name = "pytest_db"

    container_name = name
    database_name = default_database_name
    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if isolation_level == "server":
            container_name += suffix
        else:
            database_name += suffix

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_mongosh(
            _service.container,
            "print(db.adminCommand('ping').ok)",
            user=username,
            password=password,
        )
        return exit_code == 0 and output.strip().endswith(b"1")

    with docker_service.run(
        image=image,
        name=container_name,
        container_port=27017,
        env={
            "MONGO_INITDB_ROOT_USERNAME": username,
            "MONGO_INITDB_ROOT_PASSWORD": password,
        },
        check=check,
        pause=0.5,
        timeout=120,
        transient=isolation_level == "server",
    ) as service:
        yield MongoDBService(
            host=service.host,
            port=service.port,
            container=service.container,
            username=username,
            password=password,
            database=database_name,
        )


@pytest.fixture(autouse=False, scope="session")
def mongodb_image() -> str:
    return "mongo:latest"


@pytest.fixture(autouse=False, scope="session")
def mongodb_service(
    docker_service: DockerService,
    xdist_mongodb_isolation_level: XdistIsolationLevel,
    mongodb_image: str,
) -> Generator[MongoDBService, None, None]:
    with _provide_mongodb_service(docker_service, mongodb_image, "mongodb", xdist_mongodb_isolation_level) as service:
        yield service
