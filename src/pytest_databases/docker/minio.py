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


MINIO_IMAGE = "cgr.dev/chainguard/minio:latest"
MINIO_MC_IMAGE = "cgr.dev/chainguard/minio-client:latest"


@dataclass
class MinioService(ServiceContainer):
    """Service container for MinIO object storage."""

    endpoint: str
    access_key: str
    secret_key: str
    secure: bool


@pytest.fixture(scope="session")
def minio_image() -> str:
    """Default MinIO container image from Chainguard."""
    return MINIO_IMAGE


@pytest.fixture(scope="session")
def minio_client_image() -> str:
    """Default MinIO mc client container image from Chainguard."""
    return MINIO_MC_IMAGE


@pytest.fixture(scope="session")
def minio_access_key() -> str:
    return os.getenv("MINIO_ACCESS_KEY", "minio")


@pytest.fixture(scope="session")
def minio_secret_key() -> str:
    return os.getenv("MINIO_SECRET_KEY", "minio123")


@pytest.fixture(scope="session")
def minio_secure() -> bool:
    return os.getenv("MINIO_SECURE", "false").lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def xdist_minio_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def minio_default_bucket_name(xdist_minio_isolation_level: XdistIsolationLevel) -> str:
    if env_bucket := os.getenv("MINIO_DEFAULT_BUCKET_NAME"):
        return env_bucket
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_minio_isolation_level == "server":
        return f"pytest-databases-{worker_num}"
    return "pytest-databases"


@pytest.fixture(scope="session")
def minio_service(
    docker_service: DockerService,
    minio_access_key: str,
    minio_secret_key: str,
    minio_secure: bool,
    minio_default_bucket_name: str,
    xdist_minio_isolation_level: XdistIsolationLevel,
    minio_image: str = MINIO_IMAGE,
    minio_client_image: str = MINIO_MC_IMAGE,
) -> Generator[MinioService, None, None]:
    """Start a Chainguard MinIO service and create the default bucket via MC_HOST_local.

    Yields:
        MinioService: The started MinIO container service metadata.
    """

    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if minio_secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/minio/health/ready"
        if not url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)
        try:
            with urlopen(url=Request(url, method="GET"), timeout=10) as response:
                return response.status == 200
        except (URLError, ConnectionError):
            return False

    command = "server /data"
    worker_num = get_xdist_worker_num()
    name = "minio"
    transient = False

    if worker_num is not None and xdist_minio_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    env = {
        "MINIO_ROOT_USER": minio_access_key,
        "MINIO_ROOT_PASSWORD": minio_secret_key,
    }

    with docker_service.run(
        image=minio_image,
        name=name,
        command=command,
        container_port=9000,
        timeout=20,
        pause=0.5,
        env=env,
        check=check,
        transient=transient,
    ) as service:
        scheme = "https" if minio_secure else "http"
        client = docker_service._client

        try:
            client.images.get(minio_client_image)
        except ImageNotFound:
            client.images.pull(minio_client_image)

        mc_host = f"{scheme}://{minio_access_key}:{minio_secret_key}@{service.host}:{service.port}"

        with contextlib.suppress(Exception):
            client.containers.run(
                image=minio_client_image,
                command=["mb", f"local/{minio_default_bucket_name}"],
                environment={"MC_HOST_local": mc_host},
                remove=True,
                network_mode="host",
            )

        yield MinioService(
            host=service.host,
            port=service.port,
            container=service.container,
            endpoint=f"{service.host}:{service.port}",
            access_key=minio_access_key,
            secret_key=minio_secret_key,
            secure=minio_secure,
        )
