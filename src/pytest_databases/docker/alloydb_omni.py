from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import psycopg
import pytest

from pytest_databases.docker.postgres import (
    _make_connection_string,
    _provide_postgres_service,
)
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclasses.dataclass
class AlloyDBService(ServiceContainer):
    database: str
    password: str
    user: str


@pytest.fixture(scope="session")
def alloydb_omni_image() -> str:
    return "google/alloydbomni"


@pytest.fixture(scope="session")
def alloydb_omni_service(
    docker_service: DockerService,
    alloydb_omni_image: str,
) -> Generator[AlloyDBService, None, None]:
    with _provide_postgres_service(
        docker_service=docker_service,
        image=alloydb_omni_image,
        name=f"alloydb_{get_xdist_worker_num() or 0}",
        xdist_postgres_isolate="server",
    ) as service:
        yield AlloyDBService(
            host=service.host,
            port=service.port,
            password=service.password,
            database=service.database,
            user=service.user,
        )


@pytest.fixture(scope="session")
def alloydb_omni_connection(alloydb_omni_service: AlloyDBService) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=alloydb_omni_service.host,
            port=alloydb_omni_service.port,
            user=alloydb_omni_service.user,
            database=alloydb_omni_service.database,
            password=alloydb_omni_service.password,
        )
    ) as conn:
        yield conn
