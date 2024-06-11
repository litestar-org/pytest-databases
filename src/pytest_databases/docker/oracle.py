from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import oracledb
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-oracle-{simple_string_hash(__file__)}"


def oracle_responsive(host: str, port: int, service_name: str, user: str, password: str) -> bool:
    try:
        conn = oracledb.connect(
            host=host,
            port=port,
            user=user,
            service_name=service_name,
            password=password,
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM dual")
            resp = cursor.fetchone()
        return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def oracle_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def oracle_docker_services(
    oracle_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=oracle_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def oracle_user() -> str:
    return "app"


@pytest.fixture(scope="session")
def oracle_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def oracle_system_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def oracle18c_service_name() -> str:
    return "xepdb1"


@pytest.fixture(scope="session")
def oracle23c_service_name() -> str:
    return "FREEPDB1"


@pytest.fixture(scope="session")
def oracle_service_name(oracle23c_service_name: str) -> str:
    return oracle23c_service_name


@pytest.fixture(scope="session")
def oracle18c_port() -> int:
    return 1514


@pytest.fixture(scope="session")
def oracle23c_port() -> int:
    return 1513


@pytest.fixture(scope="session")
def default_oracle_service_name() -> str:
    return "oracle23c"


@pytest.fixture(scope="session")
def oracle_port(oracle23c_port: int) -> int:
    return oracle23c_port


@pytest.fixture(scope="session")
def oracle_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.oracle.yml")]


@pytest.fixture(scope="session")
def oracle_docker_ip(oracle_docker_services: DockerServiceRegistry) -> str:
    return oracle_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def oracle23c_service(
    oracle_docker_services: DockerServiceRegistry,
    oracle_docker_compose_files: list[Path],
    oracle23c_port: int,
    oracle23c_service_name: str,
    oracle_system_password: str,
    oracle_user: str,
    oracle_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["ORACLE_PASSWORD"] = oracle_password
    os.environ["ORACLE_SYSTEM_PASSWORD"] = oracle_system_password
    os.environ["ORACLE_USER"] = oracle_user
    os.environ["ORACLE23C_SERVICE_NAME"] = oracle23c_service_name
    os.environ["ORACLE23C_PORT"] = str(oracle23c_port)
    await oracle_docker_services.start(
        "oracle23c",
        docker_compose_files=oracle_docker_compose_files,
        timeout=90,
        pause=1,
        check=oracle_responsive,
        port=oracle23c_port,
        service_name=oracle23c_service_name,
        user=oracle_user,
        password=oracle_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def oracle18c_service(
    oracle_docker_services: DockerServiceRegistry,
    oracle_docker_compose_files: list[Path],
    oracle18c_port: int,
    oracle18c_service_name: str,
    oracle_system_password: str,
    oracle_user: str,
    oracle_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["ORACLE_PASSWORD"] = oracle_password
    os.environ["ORACLE_SYSTEM_PASSWORD"] = oracle_system_password
    os.environ["ORACLE_USER"] = oracle_user
    os.environ["ORACLE18C_SERVICE_NAME"] = oracle18c_service_name
    os.environ["ORACLE18C_PORT"] = str(oracle18c_port)
    await oracle_docker_services.start(
        "oracle18c",
        docker_compose_files=oracle_docker_compose_files,
        timeout=90,
        pause=1,
        check=oracle_responsive,
        port=oracle18c_port,
        service_name=oracle18c_service_name,
        user=oracle_user,
        password=oracle_password,
    )
    yield


# alias to the latest
@pytest.fixture(autouse=False, scope="session")
async def oracle_service(
    oracle_docker_services: DockerServiceRegistry,
    default_oracle_service_name: str,
    oracle_docker_compose_files: list[Path],
    oracle_port: int,
    oracle_service_name: str,
    oracle_system_password: str,
    oracle_user: str,
    oracle_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["ORACLE_PASSWORD"] = oracle_password
    os.environ["ORACLE_SYSTEM_PASSWORD"] = oracle_system_password
    os.environ["ORACLE_USER"] = oracle_user
    os.environ["ORACLE_SERVICE_NAME"] = oracle_service_name
    os.environ[f"{default_oracle_service_name.upper()}_PORT"] = str(oracle_port)
    await oracle_docker_services.start(
        name=default_oracle_service_name,
        docker_compose_files=oracle_docker_compose_files,
        timeout=90,
        pause=1,
        check=oracle_responsive,
        port=oracle_port,
        service_name=oracle_service_name,
        user=oracle_user,
        password=oracle_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def oracle_startup_connection(
    oracle_service: DockerServiceRegistry,
    oracle_docker_ip: str,
    oracle_port: int,
    oracle_service_name: str,
    oracle_user: str,
    oracle_password: str,
) -> AsyncGenerator[oracledb.AsyncConnection, None]:
    async with oracledb.connect_async(
        host=oracle_docker_ip,
        port=oracle_port,
        user=oracle_user,
        service_name=oracle_service_name,
        password=oracle_password,
    ) as db_connection:
        yield db_connection


@pytest.fixture(autouse=False, scope="session")
async def oracle18c_startup_connection(
    oracle18c_service: DockerServiceRegistry,
    oracle_docker_ip: str,
    oracle18c_port: int,
    oracle18c_service_name: str,
    oracle_user: str,
    oracle_password: str,
) -> AsyncGenerator[oracledb.AsyncConnection, None]:
    async with oracledb.connect_async(
        host=oracle_docker_ip,
        port=oracle18c_port,
        user=oracle_user,
        service_name=oracle18c_service_name,
        password=oracle_password,
    ) as db_connection:
        yield db_connection


@pytest.fixture(autouse=False, scope="session")
async def oracle23c_startup_connection(
    oracle23c_service: DockerServiceRegistry,
    oracle_docker_ip: str,
    oracle23c_port: int,
    oracle23c_service_name: str,
    oracle_user: str,
    oracle_password: str,
) -> AsyncGenerator[oracledb.AsyncConnection, None]:
    async with oracledb.connect_async(
        host=oracle_docker_ip,
        port=oracle23c_port,
        user=oracle_user,
        service_name=oracle23c_service_name,
        password=oracle_password,
    ) as db_connection:
        yield db_connection
