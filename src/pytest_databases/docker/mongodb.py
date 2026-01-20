from __future__ import annotations

import contextlib
import traceback
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pymongo
import pytest
from pymongo.errors import ConnectionFailure

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pymongo import MongoClient
    from pymongo.database import Database

    from pytest_databases._service import DockerService


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
        client: MongoClient | None = None
        try:
            client = pymongo.MongoClient(
                host=_service.host,
                port=_service.port,
                username=username,
                password=password,
                serverSelectionTimeoutMS=2000,  # Increased timeout for robust check
                connectTimeoutMS=2000,
                socketTimeoutMS=2000,
            )
            client.admin.command("ping")
        except ConnectionFailure:
            traceback.print_exc()
            return False
        else:
            return True
        finally:
            if client:
                client.close()

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
            host=service.host, port=service.port, username=username, password=password, database=database_name
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


@pytest.fixture(autouse=False, scope="session")
def mongodb_connection(mongodb_service: MongoDBService) -> Generator[MongoClient, None, None]:
    client: MongoClient | None = None
    try:
        client = pymongo.MongoClient(
            host=mongodb_service.host,
            port=mongodb_service.port,
            username=mongodb_service.username,
            password=mongodb_service.password,
        )
        yield client
    finally:
        if client:
            client.close()


@pytest.fixture(autouse=False, scope="function")
def mongodb_database(
    mongodb_connection: MongoClient, mongodb_service: MongoDBService
) -> Generator[Database, None, None]:
    """Provides a MongoDB database instance for testing.

    Yields:
        A MongoDB database instance.
    """
    db = mongodb_connection[mongodb_service.database]
    yield db
    # For a truly clean state per test, you might consider dropping the database here,
    # but it depends on the desired test isolation and speed.
    # e.g., mongodb_connection.drop_database(mongodb_service.database)
