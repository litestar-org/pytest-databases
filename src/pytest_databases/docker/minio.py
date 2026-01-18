import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from minio.api import Minio

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
    name = "minio"
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
    ) as service:
        yield MinioService(
            host=service.host,
            port=service.port,
            endpoint=f"{service.host}:{service.port}",
            access_key=minio_access_key,
            secret_key=minio_secret_key,
            secure=minio_secure,
        )


@pytest.fixture(scope="session")
def minio_client(
    minio_service: "MinioService",
    minio_default_bucket_name: str,
) -> "Generator[Minio, None, None]":
    client = Minio(
        endpoint=minio_service.endpoint,
        access_key=minio_service.access_key,
        secret_key=minio_service.secret_key,
        secure=minio_service.secure,
    )
    try:
        if not client.bucket_exists(minio_default_bucket_name):
            client.make_bucket(minio_default_bucket_name)
    except Exception as e:
        msg = f"Failed to create bucket {minio_default_bucket_name}"
        raise RuntimeError(msg) from e
    else:
        yield client
