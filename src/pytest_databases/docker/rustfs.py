"""RustFS S3-compatible object storage service fixtures."""

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

__all__ = (
    "RUSTFS_IMAGE",
    "RUSTFS_RC_IMAGE",
    "RustfsService",
    "provide_rustfs_service",
    "rustfs_access_key",
    "rustfs_default_bucket_name",
    "rustfs_image",
    "rustfs_secret_key",
    "rustfs_secure",
    "rustfs_service",
    "xdist_rustfs_isolation_level",
)

RUSTFS_IMAGE = "rustfs/rustfs:latest"
RUSTFS_RC_IMAGE = "rustfs/rc:latest"


@dataclass
class RustfsService(ServiceContainer):
    """Service container for RustFS object storage."""

    endpoint: str
    access_key: str
    secret_key: str
    secure: bool


@contextlib.contextmanager
def provide_rustfs_service(
    docker_service: DockerService,
    *,
    access_key: str,
    secret_key: str,
    secure: bool,
    default_bucket_name: str,
    isolation_level: XdistIsolationLevel,
    image: str = RUSTFS_IMAGE,
) -> Generator[RustfsService, None, None]:
    """Start a RustFS service container and provision the default bucket via ``rustfs/rc``.

    Yields:
        RustfsService: Started RustFS container service metadata.
    """

    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/health"
        if not url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)
        try:
            with urlopen(url=Request(url, method="GET"), timeout=10) as response:
                return response.status == 200
        except (URLError, ConnectionError):
            return False

    worker_num = get_xdist_worker_num()
    name = "rustfs"
    transient = False

    if worker_num is not None and isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    env = {
        "RUSTFS_ROOT_USER": access_key,
        "RUSTFS_ROOT_PASSWORD": secret_key,
    }

    with docker_service.run(
        image=image,
        name=name,
        container_port=9000,
        timeout=30,
        pause=0.5,
        env=env,
        check=check,
        transient=transient,
    ) as service:
        scheme = "https" if secure else "http"
        endpoint_url = f"{scheme}://{service.host}:{service.port}"
        client = docker_service._client

        try:
            client.images.get(RUSTFS_RC_IMAGE)
        except ImageNotFound:
            client.images.pull(RUSTFS_RC_IMAGE)

        command = [
            "sh",
            "-c",
            (f"rc alias set local {endpoint_url} {access_key} {secret_key} && rc mb local/{default_bucket_name}"),
        ]

        with contextlib.suppress(Exception):
            client.containers.run(
                image=RUSTFS_RC_IMAGE,
                command=command,
                remove=True,
                network_mode="host",
            )

        yield RustfsService(
            host=service.host,
            port=service.port,
            container=service.container,
            endpoint=f"{service.host}:{service.port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )


@pytest.fixture(scope="session")
def rustfs_image() -> str:
    """Default RustFS container image."""
    return RUSTFS_IMAGE


@pytest.fixture(scope="session")
def rustfs_access_key() -> str:
    """Default RustFS root access key."""
    return os.getenv("RUSTFS_ACCESS_KEY", "pytest-databases-rustfs")


@pytest.fixture(scope="session")
def rustfs_secret_key() -> str:
    """Default RustFS root secret key."""
    return os.getenv("RUSTFS_SECRET_KEY", "pytest-databases-rustfs-secret")


@pytest.fixture(scope="session")
def rustfs_secure() -> bool:
    """Whether RustFS connections use HTTPS."""
    return os.getenv("RUSTFS_SECURE", "false").lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def xdist_rustfs_isolation_level() -> XdistIsolationLevel:
    """Default ``pytest-xdist`` isolation level for RustFS."""
    return "database"


@pytest.fixture(scope="session")
def rustfs_default_bucket_name(xdist_rustfs_isolation_level: XdistIsolationLevel) -> str:
    """Default bucket name provisioned on startup, isolated per ``pytest-xdist`` worker."""
    if env_bucket := os.getenv("RUSTFS_DEFAULT_BUCKET_NAME"):
        return env_bucket
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_rustfs_isolation_level in {"database", "server"}:
        return f"pytest-databases-{worker_num}"
    return "pytest-databases"


@pytest.fixture(scope="session")
def rustfs_service(
    docker_service: DockerService,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    rustfs_secure: bool,
    rustfs_default_bucket_name: str,
    xdist_rustfs_isolation_level: XdistIsolationLevel,
    rustfs_image: str = RUSTFS_IMAGE,
) -> Generator[RustfsService, None, None]:
    """Start a RustFS service container and provision the default bucket.

    Yields:
        RustfsService: Started RustFS container service metadata.
    """
    with provide_rustfs_service(
        docker_service,
        access_key=rustfs_access_key,
        secret_key=rustfs_secret_key,
        secure=rustfs_secure,
        default_bucket_name=rustfs_default_bucket_name,
        isolation_level=xdist_rustfs_isolation_level,
        image=rustfs_image,
    ) as service:
        yield service
