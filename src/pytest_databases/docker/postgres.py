from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import asyncpg
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-postgres-{simple_string_hash(__file__)}"


async def postgres_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            database=database,
            password=password,
        )
    except Exception:  # noqa: BLE001
        return False

    try:
        db_open = await conn.fetchrow("SELECT 1")
        return bool(db_open is not None and db_open[0] == 1)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def postgres_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def postgres_docker_services(
    postgres_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=postgres_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def postgres_user() -> str:
    return "postgres"


@pytest.fixture(scope="session")
def postgres_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def postgres_database() -> str:
    return "postgres"


@pytest.fixture(scope="session")
def postgres11_port() -> int:
    return 5422


@pytest.fixture(scope="session")
def postgres12_port() -> int:
    return 5423


@pytest.fixture(scope="session")
def postgres13_port() -> int:
    return 5424


@pytest.fixture(scope="session")
def postgres14_port() -> int:
    return 5425


@pytest.fixture(scope="session")
def postgres15_port() -> int:
    return 5426


@pytest.fixture(scope="session")
def postgres16_port() -> int:
    return 5427


@pytest.fixture(scope="session")
def default_postgres_service_name() -> str:
    return "postgres16"


@pytest.fixture(scope="session")
def postgres_port(postgres16_port: int) -> int:
    return postgres16_port


@pytest.fixture(scope="session")
def postgres_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.postgres.yml")]


@pytest.fixture(scope="session")
def postgres_docker_ip(postgres_docker_services: DockerServiceRegistry) -> str:
    return postgres_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def postgres12_service(
    postgres_docker_services: DockerServiceRegistry,
    postgres_docker_compose_files: list[Path],
    postgres12_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ["POSTGRES12_PORT"] = str(postgres12_port)
    await postgres_docker_services.start(
        "postgres12",
        docker_compose_files=postgres_docker_compose_files,
        timeout=45,
        pause=1,
        check=postgres_responsive,
        port=postgres12_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def postgres13_service(
    postgres_docker_services: DockerServiceRegistry,
    postgres_docker_compose_files: list[Path],
    postgres13_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ["POSTGRES13_PORT"] = str(postgres13_port)
    await postgres_docker_services.start(
        "postgres13",
        docker_compose_files=postgres_docker_compose_files,
        timeout=45,
        pause=1,
        check=postgres_responsive,
        port=postgres13_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def postgres14_service(
    postgres_docker_services: DockerServiceRegistry,
    postgres_docker_compose_files: list[Path],
    postgres14_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ["POSTGRES14_PORT"] = str(postgres14_port)
    await postgres_docker_services.start(
        "postgres14",
        docker_compose_files=postgres_docker_compose_files,
        timeout=45,
        pause=1,
        check=postgres_responsive,
        port=postgres14_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def postgres15_service(
    postgres_docker_services: DockerServiceRegistry,
    postgres_docker_compose_files: list[Path],
    postgres15_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ["POSTGRES15_PORT"] = str(postgres15_port)
    await postgres_docker_services.start(
        "postgres15",
        docker_compose_files=postgres_docker_compose_files,
        timeout=45,
        pause=1,
        check=postgres_responsive,
        port=postgres15_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def postgres16_service(
    postgres_docker_services: DockerServiceRegistry,
    postgres_docker_compose_files: list[Path],
    postgres16_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ["POSTGRES16_PORT"] = str(postgres16_port)
    await postgres_docker_services.start(
        "postgres16",
        docker_compose_files=postgres_docker_compose_files,
        timeout=45,
        pause=1,
        check=postgres_responsive,
        port=postgres16_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield


# alias to the latest
@pytest.fixture(autouse=False, scope="session")
async def postgres_service(
    postgres_docker_services: DockerServiceRegistry,
    default_postgres_service_name: str,
    postgres_docker_compose_files: list[Path],
    postgres_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[DockerServiceRegistry, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ[f"{default_postgres_service_name.upper()}_PORT"] = str(postgres_port)
    await postgres_docker_services.start(
        name=default_postgres_service_name,
        docker_compose_files=postgres_docker_compose_files,
        timeout=45,
        pause=1,
        check=postgres_responsive,
        port=postgres_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield postgres_docker_services


@pytest.fixture(autouse=False, scope="session")
async def postgres_startup_connection(
    postgres_service: DockerServiceRegistry,
    postgres_docker_ip: str,
    postgres_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    conn = await asyncpg.connect(
        host=postgres_docker_ip,
        port=postgres_port,
        user=postgres_user,
        database=postgres_database,
        password=postgres_password,
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(autouse=False, scope="session")
async def postgres16_startup_connection(
    postgres16_service: DockerServiceRegistry,
    postgres_docker_ip: str,
    postgres16_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    conn = await asyncpg.connect(
        host=postgres_docker_ip,
        port=postgres16_port,
        user=postgres_user,
        database=postgres_database,
        password=postgres_password,
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(autouse=False, scope="session")
async def postgres15_startup_connection(
    postgres15_service: DockerServiceRegistry,
    postgres_docker_ip: str,
    postgres15_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    conn = await asyncpg.connect(
        host=postgres_docker_ip,
        port=postgres15_port,
        user=postgres_user,
        database=postgres_database,
        password=postgres_password,
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(autouse=False, scope="session")
async def postgres14_startup_connection(
    postgres14_service: DockerServiceRegistry,
    postgres_docker_ip: str,
    postgres14_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    conn = await asyncpg.connect(
        host=postgres_docker_ip,
        port=postgres14_port,
        user=postgres_user,
        database=postgres_database,
        password=postgres_password,
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(autouse=False, scope="session")
async def postgres13_startup_connection(
    postgres13_service: DockerServiceRegistry,
    postgres_docker_ip: str,
    postgres13_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    conn = await asyncpg.connect(
        host=postgres_docker_ip,
        port=postgres13_port,
        user=postgres_user,
        database=postgres_database,
        password=postgres_password,
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(autouse=False, scope="session")
async def postgres12_startup_connection(
    postgres12_service: DockerServiceRegistry,
    postgres_docker_ip: str,
    postgres12_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[asyncpg.Connection[asyncpg.Record], None]:
    conn = await asyncpg.connect(
        host=postgres_docker_ip,
        port=postgres12_port,
        user=postgres_user,
        database=postgres_database,
        password=postgres_password,
    )
    try:
        yield conn
    finally:
        await conn.close()
