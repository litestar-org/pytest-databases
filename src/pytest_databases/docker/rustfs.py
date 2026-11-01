"""RustFS S3-compatible object storage service fixtures."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest

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
    "create_s3_bucket",
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


def _derive_aws_v4_signing_key(secret_key: str, *, date_stamp: str, region: str, service: str) -> bytes:
    """Derive an AWS Signature Version 4 signing key."""
    key_date = hmac.new(f"AWS4{secret_key}".encode(), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode("utf-8"), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def _build_sigv4_headers(
    endpoint_url: str,
    bucket_name: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
) -> tuple[str, dict[str, str]]:
    """Build URL and SigV4 authentication headers for an S3 PUT bucket request."""
    parsed = urlsplit(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"S3 endpoint_url must be a valid http(s) URL, got {endpoint_url!r}"
        raise ValueError(msg)

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    canonical_uri = f"/{bucket_name}"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"

    canonical_headers = f"host:{parsed.netloc}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    canonical_request = (
        f"PUT\n{canonical_uri}\n\n{canonical_headers}\nhost;x-amz-content-sha256;x-amz-date\n{payload_hash}"
    )
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    signing_key = _derive_aws_v4_signing_key(secret_key, date_stamp=date_stamp, region=region, service="s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Length": "0",
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    return f"{parsed.scheme}://{parsed.netloc}{canonical_uri}", headers


def create_s3_bucket(
    endpoint_url: str,
    bucket_name: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
) -> None:
    """Create an S3 bucket idempotently via stdlib AWS SigV4 HTTP PUT without third-party SDKs."""
    bucket_url, headers = _build_sigv4_headers(
        endpoint_url,
        bucket_name,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
    )
    request = Request(bucket_url, data=None, method="PUT", headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 409 and ("BucketAlreadyOwnedByYou" in body or "BucketAlreadyExists" in body):
            return
        msg = f"Failed to create bucket {bucket_name!r}: HTTP {exc.code} - {body}"
        raise RuntimeError(msg) from exc
    except Exception as exc:
        msg = f"Failed to create bucket {bucket_name!r} on {endpoint_url}: {exc}"
        raise RuntimeError(msg) from exc

    if status not in {200, 204}:
        msg = f"Failed to create bucket {bucket_name!r}: HTTP {status}"
        raise RuntimeError(msg)


@dataclass
class RustfsService(ServiceContainer):
    """Service container for RustFS object storage."""

    endpoint: str
    access_key: str
    secret_key: str
    secure: bool

    @property
    def endpoint_url(self) -> str:
        """S3 HTTP or HTTPS endpoint URL for RustFS."""
        scheme = "https" if self.secure else "http"
        return f"{scheme}://{self.endpoint}"

    def ensure_bucket(self, bucket_name: str) -> None:
        """Ensure the specified bucket exists on the RustFS service."""
        create_s3_bucket(
            self.endpoint_url,
            bucket_name,
            access_key=self.access_key,
            secret_key=self.secret_key,
        )


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
    """Start a RustFS service container and provision the default bucket via SigV4 PUT.

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
        service_instance = RustfsService(
            host=service.host,
            port=service.port,
            container=service.container,
            endpoint=f"{service.host}:{service.port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        service_instance.ensure_bucket(default_bucket_name)
        yield service_instance


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
