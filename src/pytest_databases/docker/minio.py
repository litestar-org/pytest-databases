"""Chainguard MinIO S3-compatible object storage service fixtures."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from pytest_databases._s3 import create_s3_bucket
from pytest_databases.docker import TRUE_VALUES
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService

__all__ = (
    "MINIO_IMAGE",
    "MinioService",
    "minio_access_key",
    "minio_default_bucket_name",
    "minio_image",
    "minio_secret_key",
    "minio_secure",
    "minio_service",
    "provide_minio_service",
    "xdist_minio_isolation_level",
)

MINIO_IMAGE = "cgr.dev/chainguard/minio:latest"


@dataclass
class MinioService(ServiceContainer):
    """Service container for MinIO object storage."""

    endpoint: str
    access_key: str
    secret_key: str
    secure: bool

    @property
    def endpoint_url(self) -> str:
        """S3 endpoint URL, ``https`` when ``secure`` is set."""
        scheme = "https" if self.secure else "http"
        return f"{scheme}://{self.endpoint}"

    def ensure_bucket(self, bucket_name: str) -> None:
        """Create ``bucket_name`` unless it already exists.

        Args:
            bucket_name: Bucket to create.
        """
        create_s3_bucket(self.endpoint_url, bucket_name, access_key=self.access_key, secret_key=self.secret_key)


@contextlib.contextmanager
def provide_minio_service(
    docker_service: DockerService,
    *,
    access_key: str,
    secret_key: str,
    secure: bool,
    default_bucket_name: str,
    isolation_level: XdistIsolationLevel,
    image: str = MINIO_IMAGE,
) -> Generator[MinioService, None, None]:
    """Start a Chainguard MinIO service and create the default bucket with a SigV4-signed request.

    Yields:
        MinioService: Started MinIO container service metadata.
    """

    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/minio/health/ready"
        if not url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)
        try:
            with urlopen(url=Request(url, method="GET"), timeout=10) as response:
                return response.status == 200
        except (URLError, ConnectionError):
            return False

    worker_num = get_xdist_worker_num()
    name = "minio"
    transient = False

    if worker_num is not None and isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    env = {
        "MINIO_ROOT_USER": access_key,
        "MINIO_ROOT_PASSWORD": secret_key,
    }

    with docker_service.run(
        image=image,
        name=name,
        command="server /data",
        container_port=9000,
        timeout=20,
        pause=0.5,
        env=env,
        check=check,
        transient=transient,
    ) as service:
        minio_service = MinioService(
            host=service.host,
            port=service.port,
            container=service.container,
            endpoint=f"{service.host}:{service.port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        minio_service.ensure_bucket(default_bucket_name)
        yield minio_service


@pytest.fixture(scope="session")
def minio_image() -> str:
    """Default MinIO container image from Chainguard."""
    return MINIO_IMAGE


@pytest.fixture(scope="session")
def minio_access_key() -> str:
    """Default MinIO root access key."""
    return os.getenv("MINIO_ACCESS_KEY", "minio")


@pytest.fixture(scope="session")
def minio_secret_key() -> str:
    """Default MinIO root secret key."""
    return os.getenv("MINIO_SECRET_KEY", "minio123")


@pytest.fixture(scope="session")
def minio_secure() -> bool:
    """Whether MinIO connections use HTTPS."""
    return os.getenv("MINIO_SECURE", "false").lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def xdist_minio_isolation_level() -> XdistIsolationLevel:
    """Default ``pytest-xdist`` isolation level for MinIO."""
    return "database"


@pytest.fixture(scope="session")
def minio_default_bucket_name(xdist_minio_isolation_level: XdistIsolationLevel) -> str:
    """Default bucket name provisioned on startup, isolated per ``pytest-xdist`` worker."""
    if env_bucket := os.getenv("MINIO_DEFAULT_BUCKET_NAME"):
        return env_bucket
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_minio_isolation_level in {"database", "server"}:
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
    minio_image: str,
) -> Generator[MinioService, None, None]:
    """Start a Chainguard MinIO service and create the default bucket.

    Yields:
        MinioService: Started MinIO container service metadata.
    """
    with provide_minio_service(
        docker_service,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
        secure=minio_secure,
        default_bucket_name=minio_default_bucket_name,
        isolation_level=xdist_minio_isolation_level,
        image=minio_image,
    ) as service:
        yield service
