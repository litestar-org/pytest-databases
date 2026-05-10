from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from pytest_databases._service import DockerService


def _output_to_bytes(output: bytes | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    return b"".join(output)


@dataclass
class MariaDBService(ServiceContainer):
    db: str
    user: str
    password: str


@pytest.fixture(scope="session")
def xdist_mariadb_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def mariadb_user() -> str:
    return os.getenv("MARIADB_USER", "app")


@pytest.fixture(scope="session")
def mariadb_password() -> str:
    return os.getenv("MARIADB_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mariadb_root_password() -> str:
    return os.getenv("MARIADB_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mariadb_database() -> str:
    return os.getenv("MARIADB_DATABASE", "db")


@contextlib.contextmanager
def _provide_mariadb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    user: str,
    password: str,
    root_password: str,
    database: str,
) -> Generator[MariaDBService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if not container:
            return False

        # Attempt to run a simple SELECT 1 to ensure the server is fully ready
        res = container.exec_run(
            ["mariadb", "--user=root", f"--password={root_password}", "-e", "SELECT 1"],
        )
        return res.exit_code == 0

    worker_num = get_xdist_worker_num()
    db_name = "pytest_databases"
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if isolation_level == "server":
            name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=image,
        check=check,
        container_port=3306,
        name=name,
        env={
            "MARIADB_ROOT_PASSWORD": root_password,
            "MARIADB_PASSWORD": password,
            "MARIADB_USER": user,
            "MARIADB_DATABASE": database,
            "MARIADB_ROOT_HOST": "%",
            "LANG": "C.UTF-8",
        },
        timeout=120,
        pause=1.0,
        transient=isolation_level == "server",
    ) as service:
        # check() above only verifies root SELECT 1; that becomes true before
        # mariadb has fully provisioned the app user with the @'%' grant. Verify
        # the app user can actually reach db_name from any host before yielding,
        # otherwise tests race into 'Host not allowed' / 'access denied'.
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if container is None:
            msg = f"MariaDB container {container_name!r} disappeared after startup"
            raise RuntimeError(msg)

        setup_sql = (
            f"CREATE DATABASE IF NOT EXISTS {db_name}; "
            f"GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; "
            "FLUSH PRIVILEGES;"
        )
        verify_cmd = [
            "mariadb",
            f"--user={user}",
            f"--password={password}",
            db_name,
            "-e",
            "SELECT 1",
        ]
        last_err: bytes = b""
        for attempt in range(15):
            setup_res = container.exec_run(
                ["mariadb", "--user=root", f"--password={root_password}", "-e", setup_sql],
            )
            if setup_res.exit_code == 0:
                verify_res = container.exec_run(verify_cmd)
                if verify_res.exit_code == 0:
                    break
                last_err = _output_to_bytes(verify_res.output)
            else:
                last_err = _output_to_bytes(setup_res.output)
            time.sleep(1 + attempt * 0.5)
        else:
            msg = (
                f"MariaDB fixture {name!r}: user {user!r} could not reach database "
                f"{db_name!r} after 15 attempts. Last output: {last_err!r}"
            )
            raise RuntimeError(msg)

        yield MariaDBService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(autouse=False, scope="session")
def mariadb_113_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    with _provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.3",
        name="mariadb-11.3",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_114_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    with _provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.4",
        name="mariadb-11.4",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_122_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    with _provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:12.2",
        name="mariadb-12.2",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(mariadb_114_service: MariaDBService) -> MariaDBService:
    return mariadb_114_service
