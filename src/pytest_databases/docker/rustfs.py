"""RustFS S3-compatible object storage service fixtures."""

from __future__ import annotations

import contextlib
import http.client
import os
import ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError

import pytest

from pytest_databases.docker import TRUE_VALUES
from pytest_databases.helpers import create_s3_bucket, get_xdist_worker_num, http_request
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService

__all__ = (
    "RUSTFS_IMAGE",
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


@dataclass
class RustfsService(ServiceContainer):
    """Service container for RustFS object storage."""

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
    """Start a RustFS service container and create the default bucket with a SigV4-signed request.

    Yields:
        RustfsService: Started RustFS container service metadata.
    """

    ssl_ctx: ssl.SSLContext | None = None
    if secure:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/health"
        try:
            status, _ = http_request(url, timeout=2.0, ssl_context=ssl_ctx)
        except (URLError, TimeoutError, OSError, http.client.HTTPException):
            return False
        return status == 200

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
        rustfs_service = RustfsService(
            host=service.host,
            port=service.port,
            container=service.container,
            endpoint=f"{service.host}:{service.port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        rustfs_service.ensure_bucket(default_bucket_name)
        yield rustfs_service


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
    rustfs_image: str,
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
