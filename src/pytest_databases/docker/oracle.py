from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import oracledb
import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


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


@dataclass
class OracleService(ServiceContainer):
    user: str
    password: str
    system_password: str
    service_name: str


@contextlib.contextmanager
def _provide_oracle_service(
    docker_service: DockerService,
    image: str,
    name: str,
    service_name: str,
) -> Generator[OracleService, None, None]:
    user = "app"
    password = "super-secret"
    system_password = "super-secret"

    def check(_service: ServiceContainer) -> bool:
        try:
            conn = oracledb.connect(
                host=_service.host,
                port=_service.port,
                user=user,
                password=password,
                service_name=service_name,
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM dual")
                resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
        except Exception:  # noqa: BLE001
            return False

    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        name = f"{name}_{worker_num}"

    with docker_service.run(
        image=image,
        name=name,
        check=check,
        container_port=1521,
        timeout=60,
        env={
            "ORACLE_PASSWORD": system_password,
            "APP_USER_PASSWORD": password,
            "APP_USER": user,
        },
    ) as service:
        yield OracleService(
            host=service.host,
            port=service.port,
            system_password=system_password,
            user=user,
            password=password,
            service_name=service_name,
        )


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service(docker_service: DockerService) -> Generator[OracleService, None, None]:
    with _provide_oracle_service(
        image="gvenzl/oracle-free:23-slim-faststart",
        name="oracle23ai",
        service_name="FREEPDB1",
        docker_service=docker_service,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service(docker_service: DockerService) -> Generator[OracleService, None, None]:
    with _provide_oracle_service(
        image="gvenzl/oracle-free:23-slim-faststart",
        name="oracle18c",
        service_name="xepdb1",
        docker_service=docker_service,
    ) as service:
        yield service


# alias to the latest
@pytest.fixture(autouse=False, scope="session")
def oracle_service(oracle23ai_service: OracleService) -> OracleService:
    return oracle23ai_service


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_connection(
    oracle18c_service: OracleService,
) -> Generator[oracledb.Connection, None, None]:
    with oracledb.connect(
        host=oracle18c_service.host,
        port=oracle18c_service.port,
        user=oracle18c_service.user,
        service_name=oracle18c_service.service_name,
        password=oracle18c_service.password,
    ) as db_connection:
        yield db_connection


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_connection(
    oracle23ai_service: OracleService,
) -> Generator[oracledb.Connection, None, None]:
    with oracledb.connect(
        host=oracle23ai_service.host,
        port=oracle23ai_service.port,
        user=oracle23ai_service.user,
        service_name=oracle23ai_service.service_name,
        password=oracle23ai_service.password,
    ) as db_connection:
        yield db_connection


@pytest.fixture(autouse=False, scope="session")
def oracle_startup_connection(oracle23ai_startup_connection: oracledb.Connection) -> oracledb.Connection:
    return oracle23ai_startup_connection
