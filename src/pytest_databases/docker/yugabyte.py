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
YUGABYTE_DATABASE = "pytest_databases"
YUGABYTE_TSERVER_FLAGS = "reject_writes_min_disk_space_mb=128"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _quote_literal(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


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


@pytest.fixture(scope="session")
def yugabyte_database() -> str:
    return YUGABYTE_DATABASE


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
    password: str | None = None,
) -> tuple[int, bytes]:
    environment = {"PGPASSWORD": password} if password is not None else None
    result = container.exec_run([
        "sh",
        "-c",
        _make_ysqlsh_command(sql, database=database, user=user),
    ], environment=environment)
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _make_role_sql(user: str, password: str) -> str:
    quoted_user = _quote_identifier(user)
    quoted_password = _quote_literal(password)
    quoted_user_literal = _quote_literal(user)
    return (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = {quoted_user_literal}) THEN "
        f"CREATE ROLE {quoted_user} LOGIN PASSWORD {quoted_password}; "
        "ELSE "
        f"ALTER ROLE {quoted_user} WITH LOGIN PASSWORD {quoted_password}; "
        "END IF; "
        "END $$;"
    )


def _ensure_yugabyte_role(container: Container, user: str, password: str) -> tuple[bool, bytes]:
    exit_code, output = _exec_ysqlsh(container, _make_role_sql(user, password))
    return exit_code == 0, output


def _ensure_yugabyte_database(container: Container, database: str, user: str) -> tuple[bool, bytes]:
    quoted_database = _quote_identifier(database)
    quoted_database_literal = _quote_literal(database)
    quoted_user = _quote_identifier(user)
    exists_code, exists_output = _exec_ysqlsh(
        container,
        f"SELECT 1 FROM pg_database WHERE datname = {quoted_database_literal}",
    )
    if exists_code != 0:
        return False, exists_output

    if exists_output.strip() != b"1":
        create_code, create_output = _exec_ysqlsh(container, f"CREATE DATABASE {quoted_database} OWNER {quoted_user}")
        if create_code != 0:
            return False, create_output

    grant_code, grant_output = _exec_ysqlsh(
        container,
        f"GRANT ALL PRIVILEGES ON DATABASE {quoted_database} TO {quoted_user}",
    )
    if grant_code != 0:
        return False, grant_output

    schema_code, schema_output = _exec_ysqlsh(
        container,
        f"GRANT ALL PRIVILEGES ON SCHEMA public TO {quoted_user}",
        database=database,
    )
    return schema_code == 0, schema_output


def _verify_yugabyte_database_access(
    container: Container,
    database: str,
    user: str,
    password: str,
) -> tuple[bool, bytes]:
    exit_code, output = _exec_ysqlsh(
        container,
        "SELECT 1",
        database=database,
        user=user,
        password=password,
    )
    return exit_code == 0 and output.strip() == b"1", output


def _prepare_yugabyte_database(
    container: Container,
    container_name: str,
    database: str,
    user: str,
    password: str,
) -> None:
    last_output = b""
    for attempt in range(15):
        role_ready, role_output = _ensure_yugabyte_role(container, user, password)
        database_ready, database_output = _ensure_yugabyte_database(container, database, user) if role_ready else (False, role_output)
        access_ready, access_output = (
            _verify_yugabyte_database_access(container, database, user, password) if database_ready else (False, database_output)
        )
        if access_ready:
            return

        last_output = access_output
        time.sleep(1 + attempt * 0.5)

    msg = (
        f"Yugabyte fixture {container_name!r}: user {user!r} could not reach database "
        f"{database!r} after 15 attempts. Last output: {last_output!r}"
    )
    raise RuntimeError(msg)


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
    yugabyte_database: str,
) -> Generator[YugabyteService, None, None]:
    def yugabyte_responsive(_service: ServiceContainer) -> bool:
        container = docker_service._get_container(f"pytest_databases_{container_name}")
        if container is None:
            return False
        exit_code, output = _exec_ysqlsh(container, "SELECT 1")
        return exit_code == 0 and output.strip() == b"1"

    container_name = "yugabyte"
    db_name = yugabyte_database
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
        command=f"bin/yugabyted start --background=false --tserver_flags={YUGABYTE_TSERVER_FLAGS}",
        transient=xdist_yugabyte_isolation_level == "server",
        timeout=120,
        pause=1.0,
    ) as service:
        container = docker_service._get_container(f"pytest_databases_{container_name}")
        if container is None:
            msg = f"Yugabyte container {container_name!r} disappeared after startup"
            raise RuntimeError(msg)

        _prepare_yugabyte_database(
            container,
            container_name,
            db_name,
            yugabyte_user,
            yugabyte_password,
        )

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
