from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
import pytest

from pytest_databases._service import DockerService
from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.docker.postgres import (
    _make_connection_string,
    _provide_postgres_service,
    PostgresService as AlloyDBService,
)

__all__ = ("AlloyDBService",)


if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_service(
    docker_service: DockerService,
) -> Generator[DockerServiceRegistry, None, None]:
    with _provide_postgres_service(
        docker_service=docker_service, image="google/alloydbomni", name="alloydb-omni"
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_startup_connection(alloydb_omni_service: AlloyDBService) -> Generator[psycopg.Connection, None, None]:
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
