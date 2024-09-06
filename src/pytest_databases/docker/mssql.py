from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pymssql
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-mssql-{simple_string_hash(__file__)}"


def mssql_responsive(host: str, user: str, password: str, database: str, port: int) -> bool:
    try:
        conn = pymssql.connect(
            user=user,
            password=password,
            database=database,
            host=host,
            port=str(port),
            timeout=2,
        )
        with conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def mssql_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def mssql_docker_services(
    mssql_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=mssql_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def mssql_user() -> str:
    return "sa"


@pytest.fixture(scope="session")
def mssql_password() -> str:
    return "Super-secret1"


@pytest.fixture(scope="session")
def mssql_database() -> str:
    return "master"


@pytest.fixture(scope="session")
def mssql2022_port() -> int:
    return 4133


@pytest.fixture(scope="session")
def mssql_port(mssql2022_port: int) -> int:
    return mssql2022_port


@pytest.fixture(scope="session")
def mssql_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.mssql.yml")]


@pytest.fixture(scope="session")
def default_mssql_service_name() -> str:
    return "mssql2022"


@pytest.fixture(scope="session")
def mssql_docker_ip(mssql_docker_services: DockerServiceRegistry) -> str:
    return mssql_docker_services.docker_ip


@pytest.fixture(scope="session")
def mssql_connection_string(
    mssql_docker_ip: str, mssql_port: int, mssql_database: str, mssql_user: str, mssql_password: str
) -> str:
    return f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={mssql_docker_ip},{mssql_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"


@pytest.fixture(scope="session")
def mssql2022_connection_string(
    mssql_docker_ip: str, mssql2022_port: int, mssql_database: str, mssql_user: str, mssql_password: str
) -> str:
    return f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={mssql_docker_ip},{mssql2022_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"


@pytest.fixture(autouse=False, scope="session")
def mssql2022_service(
    mssql_docker_services: DockerServiceRegistry,
    mssql_docker_compose_files: list[Path],
    mssql_docker_ip: str,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> Generator[None, None, None]:
    os.environ["MSSQL_PASSWORD"] = mssql_password
    os.environ["MSSQL_USER"] = mssql_user
    os.environ["MSSQL_DATABASE"] = mssql_database
    os.environ["MSSQL2022_PORT"] = str(mssql2022_port)
    mssql_docker_services.start(
        "mssql2022",
        docker_compose_files=mssql_docker_compose_files,
        timeout=120,
        pause=1,
        check=mssql_responsive,
        port=mssql2022_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
def mssql_service(
    mssql_docker_services: DockerServiceRegistry,
    default_mssql_service_name: str,
    mssql_docker_compose_files: list[Path],
    mssql_docker_ip: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
    mssql_connection_string: str,
) -> Generator[None, None, None]:
    os.environ["MSSQL_PASSWORD"] = mssql_password
    os.environ["MSSQL_USER"] = mssql_user
    os.environ["MSSQL_DATABASE"] = mssql_database
    os.environ[f"{default_mssql_service_name.upper()}_PORT"] = str(mssql_port)
    mssql_docker_services.start(
        name=default_mssql_service_name,
        docker_compose_files=mssql_docker_compose_files,
        timeout=120,
        pause=1,
        check=mssql_responsive,
        port=mssql_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
def mssql_startup_connection(
    mssql_service: DockerServiceRegistry,
    mssql_docker_ip: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> Generator[pymssql.Connection, None, None]:
    with pymssql.connect(
        host=mssql_docker_ip,
        port=mssql_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
        timeout=2,
    ) as db_connection:
        yield db_connection


@pytest.fixture(autouse=False, scope="session")
def mssql2022_startup_connection(
    mssql2022_service: DockerServiceRegistry,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> Generator[pymssql.Connection, None, None]:
    with pymssql.connect(
        port=mssql2022_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
        timeout=2,
    ) as db_connection:
        yield db_connection
