from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from docker.errors import ImageNotFound

from pytest_databases.docker import TRUE_VALUES
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclass
class RustfsService(ServiceContainer):
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool


@pytest.fixture(scope="session")
def rustfs_access_key() -> str:
    return os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin")


@pytest.fixture(scope="session")
def rustfs_secret_key() -> str:
    return os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin")


@pytest.fixture(scope="session")
def rustfs_secure() -> bool:
    return os.getenv("RUSTFS_SECURE", "false").lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def xdist_rustfs_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def rustfs_default_bucket_name(xdist_rustfs_isolation_level: XdistIsolationLevel) -> str:
    if env_bucket := os.getenv("RUSTFS_DEFAULT_BUCKET_NAME"):
        return env_bucket
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_rustfs_isolation_level == "server":
        return f"pytest-databases-{worker_num}"
    return "pytest-databases"


@pytest.fixture(scope="session")
def rustfs_service(
    docker_service: "DockerService",
    rustfs_access_key: str,
    rustfs_secret_key: str,
    rustfs_secure: bool,
    rustfs_default_bucket_name: str,
    xdist_rustfs_isolation_level: XdistIsolationLevel,
) -> "Generator[RustfsService, None, None]":
    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if rustfs_secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/health"
        if not url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)
        try:
            with urlopen(url=Request(url, method="GET"), timeout=10) as response:  # noqa: S310
                return response.status == 200
        except (URLError, ConnectionError):
            return False

    worker_num = get_xdist_worker_num()
    name = "rustfs"
    transient = False

    if worker_num is not None and xdist_rustfs_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    env = {
        "RUSTFS_ROOT_USER": rustfs_access_key,
        "RUSTFS_ROOT_PASSWORD": rustfs_secret_key,
    }

    with docker_service.run(
        image="rustfs/rustfs:latest",
        name=name,
        container_port=9000,
        timeout=30,
        pause=0.5,
        env=env,
        check=check,
        transient=transient,
    ) as service:
        # Create default bucket using rustfs/rc container
        scheme = "https" if rustfs_secure else "http"
        # Since we're running from the host, we use the host's IP/port for the alias
        endpoint_url = f"{scheme}://{service.host}:{service.port}"

        # We need the Docker client to run the one-shot container
        client = docker_service._client

        # Pull the RC image first if not present
        try:
            client.images.get("rustfs/rc:latest")
        except ImageNotFound:
            client.images.pull("rustfs/rc:latest")

        # Run rc container to create bucket
        # Command: rc alias set local <url> <access> <secret> && rc mb local/<bucket>
        # Note: We use --ignore-existing for 'mb' if available, or just ignore errors.
        # However, it's safer to just run and ignore errors.
        command = [
            "sh",
            "-c",
            (
                f"rc alias set local {endpoint_url} {rustfs_access_key} {rustfs_secret_key} && "
                f"rc mb local/{rustfs_default_bucket_name}"
            ),
        ]

        with contextlib.suppress(Exception):
            client.containers.run(
                image="rustfs/rc:latest",
                command=command,
                remove=True,
                network_mode="host",  # Use host network to connect to the mapped port
            )

        yield RustfsService(

            host=service.host,
            port=service.port,
            endpoint=f"{service.host}:{service.port}",
            access_key=rustfs_access_key,
            secret_key=rustfs_secret_key,
            secure=rustfs_secure,
        )
