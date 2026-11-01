"""Chainguard MinIO S3-compatible object storage service fixtures."""

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
    "MINIO_IMAGE",
    "MINIO_MC_IMAGE",
    "MinioService",
    "create_s3_bucket",
    "minio_access_key",
    "minio_client_image",
    "minio_default_bucket_name",
    "minio_image",
    "minio_secret_key",
    "minio_secure",
    "minio_service",
    "provide_minio_service",
    "xdist_minio_isolation_level",
)

MINIO_IMAGE = "cgr.dev/chainguard/minio:latest"
MINIO_MC_IMAGE = "cgr.dev/chainguard/minio-client:latest"


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
class MinioService(ServiceContainer):
    """Service container for MinIO object storage."""

    endpoint: str
    access_key: str
    secret_key: str
    secure: bool

    @property
    def endpoint_url(self) -> str:
        """S3 HTTP or HTTPS endpoint URL for MinIO."""
        scheme = "https" if self.secure else "http"
        return f"{scheme}://{self.endpoint}"

    def ensure_bucket(self, bucket_name: str) -> None:
        """Ensure the specified bucket exists on the MinIO service."""
        create_s3_bucket(
            self.endpoint_url,
            bucket_name,
            access_key=self.access_key,
            secret_key=self.secret_key,
        )


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
    client_image: str = MINIO_MC_IMAGE,
) -> Generator[MinioService, None, None]:
    """Start a Chainguard MinIO service and provision the default bucket via SigV4 PUT.

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
        service_instance = MinioService(
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
def minio_image() -> str:
    """Default MinIO container image from Chainguard."""
    return MINIO_IMAGE


@pytest.fixture(scope="session")
def minio_client_image() -> str:
    """Default MinIO ``mc`` client container image from Chainguard."""
    return MINIO_MC_IMAGE


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
    minio_image: str = MINIO_IMAGE,
    minio_client_image: str = MINIO_MC_IMAGE,
) -> Generator[MinioService, None, None]:
    """Start a Chainguard MinIO service and create the default bucket via ``MC_HOST_local``.

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
        client_image=minio_client_image,
    ) as service:
        yield service
