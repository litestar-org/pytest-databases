from __future__ import annotations

import contextlib
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService


ORACLE_USER = "app"
ORACLE_PASSWORD = "super-secret"
ORACLE_SYSTEM_PASSWORD = "super-secret"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _normalize_sqlplus_statement(sql: str) -> str:
    statement = sql.strip()
    if not statement.endswith(";"):
        statement = f"{statement};"
    return statement


def _exec_sqlplus(
    container: Container,
    user: str,
    password: str,
    service_name: str,
    sql: str,
) -> tuple[int, bytes]:
    script = "\n".join([
        "SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF",
        "WHENEVER OSERROR EXIT 9",
        "WHENEVER SQLERROR EXIT SQL.SQLCODE",
        _normalize_sqlplus_statement(sql),
        "EXIT",
        "",
    ])
    connect_string = f"{user}/{password}@//localhost:1521/{service_name}"
    command = f"printf '%s' {shlex.quote(script)} | sqlplus -L -S {shlex.quote(connect_string)}"
    result = container.exec_run(["bash", "-lc", command])
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


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
    user: str,
    password: str,
    system_password: str,
) -> Generator[OracleService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_sqlplus(
            _service.container,
            user,
            password,
            service_name,
            "SELECT 1 FROM dual",
        )
        return exit_code == 0 and output.strip() == b"1"

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
            container=service.container,
            system_password=system_password,
            user=user,
            password=password,
            service_name=service_name,
        )


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_image() -> str:
    return "gvenzl/oracle-free:23-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service_name() -> str:
    return "FREEPDB1"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_image() -> str:
    return "gvenzl/oracle-xe:18-slim-faststart"


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service_name() -> str:
    return "xepdb1"


@pytest.fixture(autouse=False, scope="session")
def oracle_user() -> str:
    return ORACLE_USER


@pytest.fixture(autouse=False, scope="session")
def oracle_password() -> str:
    return ORACLE_PASSWORD


@pytest.fixture(autouse=False, scope="session")
def oracle_system_password() -> str:
    return ORACLE_SYSTEM_PASSWORD


@pytest.fixture(autouse=False, scope="session")
def oracle_23ai_service(
    docker_service: DockerService,
    oracle_23ai_image: str,
    oracle_23ai_service_name: str,
    oracle_user: str,
    oracle_password: str,
    oracle_system_password: str,
) -> Generator[OracleService, None, None]:
    with _provide_oracle_service(
        image=oracle_23ai_image,
        name="oracle23ai",
        service_name=oracle_23ai_service_name,
        user=oracle_user,
        password=oracle_password,
        system_password=oracle_system_password,
        docker_service=docker_service,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def oracle_18c_service(
    docker_service: DockerService,
    oracle_18c_image: str,
    oracle_18c_service_name: str,
    oracle_user: str,
    oracle_password: str,
    oracle_system_password: str,
) -> Generator[OracleService, None, None]:
    with _provide_oracle_service(
        image=oracle_18c_image,
        name="oracle18c",
        service_name=oracle_18c_service_name,
        user=oracle_user,
        password=oracle_password,
        system_password=oracle_system_password,
        docker_service=docker_service,
    ) as service:
        yield service


# alias to the latest
@pytest.fixture(autouse=False, scope="session")
def oracle_service(oracle_23ai_service: OracleService) -> OracleService:
    return oracle_23ai_service
