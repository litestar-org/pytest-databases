"""MongoDB container service fixtures."""

from __future__ import annotations

import contextlib
import importlib
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

__all__ = (
    "MongoDBService",
    "mongodb_connection",
    "mongodb_database",
    "mongodb_image",
    "mongodb_service",
    "provide_mongodb_service",
    "xdist_mongodb_isolation_level",
)


@dataclass
class MongoDBService(ServiceContainer):
    """Service handle for a running MongoDB container."""

    username: str
    password: str
    database: str


@contextlib.contextmanager
def provide_mongodb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[MongoDBService, None, None]:
    """Start and manage a MongoDB container service.

    Yields:
        Active MongoDBService instance.
    """
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


@pytest.fixture(scope="session")
def xdist_mongodb_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for MongoDB.

    Returns:
        Default isolation level string.
    """
    return "database"


@pytest.fixture(autouse=False, scope="session")
def mongodb_image() -> str:
    """Return the MongoDB container image.

    Returns:
        Container image tag.
    """
    return "mongo:latest"


@pytest.fixture(autouse=False, scope="session")
def mongodb_service(
    docker_service: DockerService,
    xdist_mongodb_isolation_level: XdistIsolationLevel,
    mongodb_image: str,
) -> Generator[MongoDBService, None, None]:
    """Provide a running MongoDB container service.

    Yields:
        Active MongoDBService instance.
    """
    with provide_mongodb_service(docker_service, mongodb_image, "mongodb", xdist_mongodb_isolation_level) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mongodb_connection(mongodb_service: MongoDBService) -> Generator[Any, None, None]:
    """Provide a deprecated pymongo MongoClient connected to MongoDB.

    Yields:
        Active pymongo MongoClient instance.
    """
    warnings.warn(
        "'mongodb_connection' is deprecated and will be removed in a future release. "
        "Use 'mongodb_service' and instantiate your pymongo client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    pymongo = importlib.import_module("pymongo")
    client = pymongo.MongoClient(
        host=mongodb_service.host,
        port=mongodb_service.port,
        username=mongodb_service.username,
        password=mongodb_service.password,
    )
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(autouse=False, scope="function")
def mongodb_database(
    mongodb_connection: Any,
    mongodb_service: MongoDBService,
) -> Generator[Any, None, None]:
    """Provide a deprecated pymongo Database instance for testing.

    Yields:
        Active pymongo Database instance.
    """
    warnings.warn(
        "'mongodb_database' is deprecated and will be removed in a future release. "
        "Use 'mongodb_service' and instantiate your pymongo client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    yield mongodb_connection[mongodb_service.database]


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
    return exit_code, exec_output_to_bytes(result.output)
