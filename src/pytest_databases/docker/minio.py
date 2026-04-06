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
class MinioService(ServiceContainer):
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool


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
    docker_service: "DockerService",
    minio_access_key: str,
    minio_secret_key: str,
    minio_secure: bool,
    minio_default_bucket_name: str,
    xdist_minio_isolation_level: XdistIsolationLevel,
) -> "Generator[MinioService, None, None]":
    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if minio_secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/minio/health/ready"
        if not url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)
        try:
            with urlopen(url=Request(url, method="GET"), timeout=10) as response:  # noqa: S310
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
        image="quay.io/minio/minio",
        name=name,
        command=command,
        container_port=9000,
        timeout=20,
        pause=0.5,
        env=env,
        check=check,
        transient=transient,
    ) as service:
        # Create default bucket using minio/mc container
        scheme = "https" if minio_secure else "http"
        endpoint_url = f"{scheme}://{service.host}:{service.port}"

        client = docker_service._client

        try:
            client.images.get("minio/mc:latest")
        except ImageNotFound:
            client.images.pull("minio/mc:latest")

        command = " ".join([
            "sh",
            "-c",
            (
                f"mc alias set local {endpoint_url} {minio_access_key} {minio_secret_key} && "
                f"mc mb local/{minio_default_bucket_name}"
            ),
        ])

        with contextlib.suppress(Exception):
            client.containers.run(
                image="minio/mc:latest",
                command=command,
                remove=True,
                network_mode="host",
            )

        yield MinioService(
            host=service.host,
            port=service.port,
            endpoint=f"{service.host}:{service.port}",
            access_key=minio_access_key,
            secret_key=minio_secret_key,
            secure=minio_secure,
        )
