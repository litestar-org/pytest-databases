from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from docker.errors import ContainerError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel


YUGABYTE_USER = "yugabyte"
YUGABYTE_PASSWORD = "yugabyte"
YUGABYTE_DB = "yugabyte"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


@pytest.fixture(scope="session")
def xdist_yugabyte_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclass
class YugabyteService(ServiceContainer):
    database: str
    user: str
    password: str


@pytest.fixture(scope="session")
def yugabyte_image() -> str:
    return "software.yugabyte.com/yugabytedb/yugabyte:latest"


@pytest.fixture(scope="session")
def yugabyte_user() -> str:
    return YUGABYTE_USER


@pytest.fixture(scope="session")
def yugabyte_password() -> str:
    return YUGABYTE_PASSWORD


def _make_ysqlsh_command(
    sql: str,
    *,
    database: str = YUGABYTE_DB,
    user: str = YUGABYTE_USER,
    host: str = "$(hostname)",
    port: int | None = None,
) -> str:
    command_parts = [
        "bin/ysqlsh",
        f"-h {host}",
    ]
    if port is not None:
        command_parts.append(f"-p {port}")
    command_parts.extend([
        f"-U {shlex.quote(user)}",
        f"-d {shlex.quote(database)}",
        "-tAc",
        shlex.quote(sql),
    ])
    return " ".join(command_parts)


def _exec_ysqlsh(
    container: Container,
    sql: str,
    *,
    database: str = YUGABYTE_DB,
    user: str = YUGABYTE_USER,
) -> tuple[int, bytes]:
    result = container.exec_run([
        "sh",
        "-c",
        _make_ysqlsh_command(sql, database=database, user=user),
    ])
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _validate_mapped_endpoint(
    docker_service: DockerService,
    image: str,
    service: ServiceContainer,
    database: str,
    user: str,
    password: str,
) -> tuple[int, bytes]:
    try:
        output = docker_service._client.containers.run(
            image=image,
            command=[
                "sh",
                "-c",
                _make_ysqlsh_command(
                    "SELECT 1",
                    database=database,
                    user=user,
                    host=service.host,
                    port=service.port,
                ),
            ],
            environment={"PGPASSWORD": password},
            network_mode="host",
            remove=True,
        )
    except ContainerError as exc:
        return exc.exit_status, _output_to_bytes(exc.stderr) if exc.stderr else str(exc).encode()
    return 0, _output_to_bytes(output)


@pytest.fixture(scope="session")
def yugabyte_service(
    docker_service: "DockerService",
    xdist_yugabyte_isolation_level: XdistIsolationLevel,
    yugabyte_image: str,
    yugabyte_user: str,
    yugabyte_password: str,
) -> Generator[YugabyteService, None, None]:
    def yugabyte_responsive(_service: ServiceContainer) -> bool:
        container = docker_service._get_container(f"pytest_databases_{container_name}")
        if container is None:
            return False
        exit_code, output = _exec_ysqlsh(container, "SELECT 1", user=yugabyte_user)
        return exit_code == 0 and output.strip() == b"1"

    container_name = "yugabyte"
    db_name = "pytest_databases"
    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_yugabyte_isolation_level == "server":
            container_name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=yugabyte_image,
        container_port=5433,  # YugabyteDB YSQL port
        check=yugabyte_responsive,
        name=container_name,
        command="bin/yugabyted start --background=false",
        transient=xdist_yugabyte_isolation_level == "server",
        timeout=120,
        pause=1.0,
    ) as service:
        container = docker_service._get_container(f"pytest_databases_{container_name}")
        if container is None:
            msg = f"Yugabyte container {container_name!r} disappeared after startup"
            raise RuntimeError(msg)

        last_output = b""
        for attempt in range(15):
            exists_code, exists_output = _exec_ysqlsh(
                container,
                f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'",
            )
            if exists_code == 0 and exists_output.strip() == b"1":
                break

            create_code, create_output = _exec_ysqlsh(container, f"CREATE DATABASE {db_name}")
            if create_code == 0:
                verify_code, verify_output = _exec_ysqlsh(
                    container,
                    f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'",
                )
                if verify_code == 0 and verify_output.strip() == b"1":
                    break
                last_output = verify_output
            else:
                last_output = create_output
            time.sleep(1 + attempt * 0.5)
        else:
            msg = (
                f"Yugabyte fixture {container_name!r}: database {db_name!r} was not ready after "
                f"15 attempts. Last output: {last_output!r}"
            )
            raise RuntimeError(msg)

        last_output = b""
        for attempt in range(5):
            endpoint_code, endpoint_output = _validate_mapped_endpoint(
                docker_service,
                yugabyte_image,
                service,
                db_name,
                yugabyte_user,
                yugabyte_password,
            )
            if endpoint_code == 0 and endpoint_output.strip() == b"1":
                break
            last_output = endpoint_output
            time.sleep(1 + attempt * 0.5)
        else:
            msg = (
                f"Yugabyte fixture {container_name!r}: mapped endpoint {service.host}:{service.port} "
                f"was not ready after 5 attempts. Last output: {last_output!r}"
            )
            raise RuntimeError(msg)

        yield YugabyteService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            user=yugabyte_user,
            password=yugabyte_password,
        )
