from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator

import pymysql
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.docker.mysql import mysql_responsive
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-mariadb-{simple_string_hash(__file__)}"


@pytest.fixture(scope="session")
def mariadb_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def mariadb_docker_services(
    mariadb_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=mariadb_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def mariadb_user() -> str:
    return "app"


@pytest.fixture(scope="session")
def mariadb_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def mariadb_root_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def mariadb_database() -> str:
    return "db"


@pytest.fixture(scope="session")
def mariadb113_port() -> int:
    return 3359


@pytest.fixture(scope="session")
def default_mariadb_service_name() -> str:
    return "mariadb113"


@pytest.fixture(scope="session")
def mariadb_port(mariadb113_port: int) -> int:
    return mariadb113_port


@pytest.fixture(scope="session")
def mariadb_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.mariadb.yml")]


@pytest.fixture(scope="session")
def mariadb_docker_ip(mariadb_docker_services: DockerServiceRegistry) -> str:
    return mariadb_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
def mariadb113_service(
    mariadb_docker_services: DockerServiceRegistry,
    mariadb_docker_compose_files: list[Path],
    mariadb113_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
) -> Generator[None, None, None]:
    os.environ["MARIADB_ROOT_PASSWORD"] = mariadb_root_password
    os.environ["MARIADB_PASSWORD"] = mariadb_password
    os.environ["MARIADB_USER"] = mariadb_user
    os.environ["MARIADB_DATABASE"] = mariadb_database
    os.environ["MARIADB113_PORT"] = str(mariadb113_port)
    mariadb_docker_services.start(
        "mariadb113",
        docker_compose_files=mariadb_docker_compose_files,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mariadb113_port,
        database=mariadb_database,
        user=mariadb_user,
        password=mariadb_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(
    mariadb_docker_services: DockerServiceRegistry,
    default_mariadb_service_name: str,
    mariadb_docker_compose_files: list[Path],
    mariadb_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
) -> Generator[None, None, None]:
    os.environ["MARIADB_ROOT_PASSWORD"] = mariadb_root_password
    os.environ["MARIADB_PASSWORD"] = mariadb_password
    os.environ["MARIADB_USER"] = mariadb_user
    os.environ["MARIADB_DATABASE"] = mariadb_database
    os.environ[f"{default_mariadb_service_name.upper()}_PORT"] = str(mariadb_port)
    mariadb_docker_services.start(
        name=default_mariadb_service_name,
        docker_compose_files=mariadb_docker_compose_files,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mariadb_port,
        database=mariadb_database,
        user=mariadb_user,
        password=mariadb_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
def mariadb_startup_connection(
    mariadb_service: DockerServiceRegistry,
    mariadb_docker_ip: str,
    mariadb_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> Generator[Any, None, None]:
    with pymysql.connect(
        host=mariadb_docker_ip,
        port=mariadb_port,
        user=mariadb_user,
        database=mariadb_database,
        password=mariadb_password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mariadb113_startup_connection(
    mariadb113_service: DockerServiceRegistry,
    mariadb_docker_ip: str,
    mariadb113_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> Generator[Any, None, None]:
    with pymysql.connect(
        host=mariadb_docker_ip,
        port=mariadb113_port,
        user=mariadb_user,
        database=mariadb_database,
        password=mariadb_password,
    ) as conn:
        yield conn
