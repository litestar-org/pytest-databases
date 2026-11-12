"""Floci multi-cloud (GCP, OCI, AWS, Azure) emulator container fixtures and stdlib HTTP helpers.

Each Floci image serves one cloud on its own gateway port and health path, listed in ``FLOCI_CONTAINER_PORTS`` and
``FLOCI_HEALTH_PATHS``.
"""

from __future__ import annotations

import email.message
import email.utils
import hashlib
import html
import http.client
import http.server
import io
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.parsers.expat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Literal

import pytest

from pytest_databases.helpers import (
    TRUE_VALUES,
    create_s3_bucket,
    get_xdist_worker_num,
    http_get_json,
    http_request,
    read_http_handler_body,
    send_http_request,
)
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

__all__ = (
    "DEFAULT_FLOCI_AWS_IMAGE",
    "DEFAULT_FLOCI_AZ_IMAGE",
    "DEFAULT_FLOCI_GCP_IMAGE",
    "DEFAULT_FLOCI_OCI_COMPARTMENT_ID",
    "DEFAULT_FLOCI_OCI_IMAGE",
    "DEFAULT_FLOCI_OCI_NAMESPACE",
    "FLOCI_CONTAINER_PORTS",
    "FLOCI_HEALTH_PATHS",
    "FlociAWSService",
    "FlociAzureService",
    "FlociCloud",
    "FlociGCPService",
    "FlociOCIService",
    "FlociService",
    "check_floci_health",
    "ensure_gcs_bucket",
    "ensure_oci_bucket",
    "floci_aws_access_key",
    "floci_aws_image",
    "floci_aws_region",
    "floci_aws_secret_key",
    "floci_aws_service",
    "floci_az_account_key",
    "floci_az_account_name",
    "floci_az_image",
    "floci_az_service",
    "floci_gcp_compat_proxy",
    "floci_gcp_image",
    "floci_gcp_project",
    "floci_gcp_service",
    "floci_oci_compartment_id",
    "floci_oci_image",
    "floci_oci_namespace",
    "floci_oci_region",
    "floci_oci_service",
    "floci_resource_prefix",
    "provide_floci_container",
    "provide_floci_gcp_service",
    "xdist_floci_isolation_level",
)

FlociCloud = Literal["aws", "azure", "gcp", "oci"]

FLOCI_CONTAINER_PORTS: Final[dict[FlociCloud, int]] = {"aws": 4566, "azure": 4577, "gcp": 4588, "oci": 4599}
FLOCI_HEALTH_PATHS: Final[dict[FlociCloud, str]] = {
    "aws": "/_floci/health",
    "azure": "/_floci/health",
    "gcp": "/_floci-gcp/health",
    "oci": "/_floci-oci/health",
}
DEFAULT_FLOCI_AWS_IMAGE = "floci/floci:2.4.0"
DEFAULT_FLOCI_AZ_IMAGE = "floci/floci-az:0.16.0"
DEFAULT_FLOCI_GCP_IMAGE = "floci/floci-gcp:0.12.0"
DEFAULT_FLOCI_OCI_IMAGE = "floci/floci-oci:0.6.0"
DEFAULT_FLOCI_OCI_NAMESPACE = "floci-local"
DEFAULT_FLOCI_OCI_COMPARTMENT_ID = "ocid1.tenancy.oc1..flocilocaltenancy0000000000000000000000000000000000000000"
_AZURITE_DEFAULT_ACCOUNT = "devstoreaccount1"
_AZURITE_DEFAULT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
_HOP_BY_HOP_REQUEST_HEADERS = frozenset({
    "accept-encoding",
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
})
_HOP_BY_HOP_RESPONSE_HEADERS = frozenset({"connection", "content-encoding", "content-length", "transfer-encoding"})


@dataclass
class FlociService(ServiceContainer):
    """Base connection metadata for a Floci cloud emulator container."""

    endpoint_url: str
    resource_prefix: str


@dataclass
class FlociGCPService(FlociService):
    """Connection metadata and helpers for a Floci GCP emulator (GCS, Pub/Sub, Firestore, Bigtable, KMS, Secret Manager)."""

    project: str

    @property
    def storage_emulator_host(self) -> str:
        """The HTTP URL value suitable for ``STORAGE_EMULATOR_HOST``."""
        return self.endpoint_url

    @property
    def pubsub_emulator_host(self) -> str:
        """The ``host:port`` value suitable for ``PUBSUB_EMULATOR_HOST``."""
        return f"{self.host}:{self.port}"

    def ensure_bucket(self, bucket_name: str) -> dict[str, Any]:
        """Create a GCS bucket on the running Floci GCP emulator without a host SDK."""
        return ensure_gcs_bucket(self.host, self.port, bucket_name, project=self.project)


@dataclass
class FlociOCIService(FlociService):
    """Connection metadata and helpers for a Floci OCI emulator (Object Storage, Queue, Vault, Secrets, Streaming)."""

    namespace: str
    region: str
    compartment_id: str

    def ensure_bucket(self, bucket_name: str) -> dict[str, Any]:
        """Create an OCI Object Storage bucket on the running Floci OCI emulator without a host SDK."""
        return ensure_oci_bucket(
            self.host,
            self.port,
            self.namespace,
            bucket_name,
            compartment_id=self.compartment_id,
        )


@dataclass
class FlociAWSService(FlociService):
    """Connection metadata and S3 bucket helper for a Floci AWS emulator (S3, SQS, SNS, DynamoDB, Secrets Manager)."""

    region: str
    access_key: str
    secret_key: str

    def ensure_bucket(self, bucket_name: str) -> None:
        """Create ``bucket_name`` idempotently on the running Floci AWS emulator via stdlib SigV4 ``PUT``."""
        create_s3_bucket(
            self.endpoint_url,
            bucket_name,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
        )


@dataclass
class FlociAzureService(FlociService):
    """Connection metadata for a Floci Azure emulator (Blob Storage, Queue Storage, Service Bus, Key Vault, Cosmos DB)."""

    account_name: str
    account_key: str

    @property
    def blob_endpoint(self) -> str:
        """The path-style Azure Blob Storage endpoint URL."""
        return f"{self.endpoint_url}/{self.account_name}"


def check_floci_health(
    host: str,
    port: int,
    health_path: str = FLOCI_HEALTH_PATHS["aws"],
    *,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    """Probe a Floci health endpoint.

    Args:
        host: Mapped container host address.
        port: Mapped container gateway port.
        health_path: Health endpoint path of the image, one of ``FLOCI_HEALTH_PATHS``.
        timeout: HTTP request timeout in seconds.

    Returns:
        The health JSON object when the endpoint answers HTTP 200 with a JSON object, otherwise ``None``.
    """
    payload = http_get_json(f"http://{host}:{port}{health_path}", timeout=timeout)
    return payload if isinstance(payload, dict) else None


def ensure_gcs_bucket(
    host: str,
    port: int,
    bucket_name: str,
    *,
    project: str = "pytest-databases",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Create a Google Cloud Storage bucket on a Floci GCP emulator via stdlib HTTP.

    An existing bucket (HTTP 409) is not an error.

    Args:
        host: Mapped container host address.
        port: Mapped container gateway port.
        bucket_name: Name of the GCS bucket to create.
        project: GCP project ID.
        timeout: HTTP request timeout in seconds.

    Returns:
        Bucket metadata returned by the emulator, or ``{"name", "project"}`` when the bucket already existed.
    """
    encoded_project = urllib.parse.quote(project, safe="")
    return _post_json(
        f"http://{host}:{port}/storage/v1/b?project={encoded_project}",
        {"name": bucket_name},
        existing={"name": bucket_name, "project": project},
        timeout=timeout,
    )


def ensure_oci_bucket(
    host: str,
    port: int,
    namespace: str,
    bucket_name: str,
    *,
    compartment_id: str = DEFAULT_FLOCI_OCI_COMPARTMENT_ID,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Create an Oracle Cloud Infrastructure Object Storage bucket on a Floci OCI emulator via stdlib HTTP.

    Floci OCI accepts unsigned requests and attributes them to its local tenancy, whose Object Storage namespace is
    ``DEFAULT_FLOCI_OCI_NAMESPACE`` and whose root compartment is ``DEFAULT_FLOCI_OCI_COMPARTMENT_ID``. An existing
    bucket (HTTP 409) is not an error.

    Args:
        host: Mapped container host address.
        port: Mapped container gateway port.
        namespace: OCI Object Storage namespace.
        bucket_name: Name of the OCI bucket to create.
        compartment_id: OCI compartment OCID that owns the bucket.
        timeout: HTTP request timeout in seconds.

    Returns:
        Bucket metadata returned by the emulator, or ``{"name", "namespace"}`` when the bucket already existed.
    """
    encoded_ns = urllib.parse.quote(namespace, safe="")
    return _post_json(
        f"http://{host}:{port}/n/{encoded_ns}/b/",
        {"name": bucket_name, "compartmentId": compartment_id},
        existing={"name": bucket_name, "namespace": namespace},
        timeout=timeout,
    )


@contextmanager
def provide_floci_container(
    container_service: ContainerService,
    *,
    image: str,
    name: str,
    container_port: int,
    health_path: str,
    isolation_level: XdistIsolationLevel = "database",
) -> Generator[ServiceContainer, None, None]:
    """Start and yield a ready Floci emulator container.

    Args:
        container_service: Container runtime service.
        image: Floci image to run.
        name: Base container name; ``_<worker number>`` is appended under xdist with ``server`` isolation.
        container_port: Gateway port inside the container, one of ``FLOCI_CONTAINER_PORTS``.
        health_path: Health endpoint path, one of ``FLOCI_HEALTH_PATHS``.
        isolation_level: pytest-xdist isolation level.

    Yields:
        A ready ServiceContainer instance.
    """
    worker_num = get_xdist_worker_num()
    transient = False
    if worker_num is not None and isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    with container_service.run(
        image=image,
        name=name,
        container_port=container_port,
        check=partial(_is_floci_ready, health_path=health_path),
        timeout=60,
        pause=0.25,
        transient=transient,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def xdist_floci_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for Floci emulators."""
    return "database"


@pytest.fixture(scope="session")
def floci_resource_prefix() -> str:
    """Provide a worker-scoped resource name prefix for Floci emulators."""
    if value := os.getenv("FLOCI_RESOURCE_PREFIX"):
        return value
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return "pytest-databases-"
    return f"pytest-databases-{worker_num}-"


@pytest.fixture(scope="session")
def floci_gcp_image() -> str:
    """Provide the Floci GCP emulator container image."""
    return os.getenv("FLOCI_GCP_IMAGE", DEFAULT_FLOCI_GCP_IMAGE)


@pytest.fixture(scope="session")
def floci_gcp_project() -> str:
    """Provide a worker-scoped GCP project ID for Floci GCP tests."""
    if value := os.getenv("FLOCI_GCP_PROJECT"):
        return value
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return "pytest-databases"
    return f"pytest-databases-{worker_num}"


@contextmanager
def provide_floci_gcp_service(
    container_service: ContainerService,
    *,
    image: str = DEFAULT_FLOCI_GCP_IMAGE,
    project: str = "pytest-databases",
    resource_prefix: str = "pytest-databases-",
    isolation_level: XdistIsolationLevel = "database",
    compat_proxy: bool = True,
) -> Generator[FlociGCPService, None, None]:
    """Start Floci GCP and optionally front it with the GCS XML/JSON compatibility proxy.

    Yields:
        A configured FlociGCPService instance.
    """
    with provide_floci_container(
        container_service,
        image=image,
        name="floci_gcp",
        container_port=FLOCI_CONTAINER_PORTS["gcp"],
        health_path=FLOCI_HEALTH_PATHS["gcp"],
        isolation_level=isolation_level,
    ) as service:
        if compat_proxy:
            with _start_floci_gcp_compat_proxy(service.host, service.port) as (proxy_host, proxy_port):
                yield FlociGCPService(
                    container=service.container,
                    host=proxy_host,
                    port=proxy_port,
                    endpoint_url=f"http://{proxy_host}:{proxy_port}",
                    resource_prefix=resource_prefix,
                    project=project,
                )
        else:
            yield FlociGCPService(
                container=service.container,
                host=service.host,
                port=service.port,
                endpoint_url=f"http://{service.host}:{service.port}",
                resource_prefix=resource_prefix,
                project=project,
            )


@pytest.fixture(scope="session")
def floci_gcp_compat_proxy() -> bool:
    """Return whether ``floci_gcp_service`` starts the GCS compatibility proxy."""
    raw = os.getenv("FLOCI_GCP_COMPAT_PROXY")
    if raw is None:
        return True
    return raw.strip().lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def floci_gcp_service(
    container_service: ContainerService,
    floci_gcp_image: str,
    floci_gcp_project: str,
    floci_resource_prefix: str,
    xdist_floci_isolation_level: XdistIsolationLevel,
    floci_gcp_compat_proxy: bool,
) -> Generator[FlociGCPService, None, None]:
    """Start and yield a ready Floci GCP emulator service container.

    Yields:
        A configured FlociGCPService instance.
    """
    with provide_floci_gcp_service(
        container_service,
        image=floci_gcp_image,
        project=floci_gcp_project,
        resource_prefix=floci_resource_prefix,
        isolation_level=xdist_floci_isolation_level,
        compat_proxy=floci_gcp_compat_proxy,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def floci_oci_image() -> str:
    """Provide the Floci OCI emulator container image."""
    return os.getenv("FLOCI_OCI_IMAGE", DEFAULT_FLOCI_OCI_IMAGE)


@pytest.fixture(scope="session")
def floci_oci_namespace() -> str:
    """Provide the OCI Object Storage namespace of the Floci OCI local tenancy."""
    return os.getenv("FLOCI_OCI_NAMESPACE", DEFAULT_FLOCI_OCI_NAMESPACE)


@pytest.fixture(scope="session")
def floci_oci_region() -> str:
    """Provide the default OCI region for the Floci OCI emulator."""
    return os.getenv("FLOCI_OCI_REGION", "us-ashburn-1")


@pytest.fixture(scope="session")
def floci_oci_compartment_id() -> str:
    """Provide the compartment OCID for Floci OCI resources (the local tenancy root compartment)."""
    return os.getenv("FLOCI_OCI_COMPARTMENT_ID", DEFAULT_FLOCI_OCI_COMPARTMENT_ID)


@pytest.fixture(scope="session")
def floci_oci_service(
    container_service: ContainerService,
    floci_oci_image: str,
    floci_oci_namespace: str,
    floci_oci_region: str,
    floci_oci_compartment_id: str,
    floci_resource_prefix: str,
    xdist_floci_isolation_level: XdistIsolationLevel,
) -> Generator[FlociOCIService, None, None]:
    """Start and yield a ready Floci OCI emulator service container.

    Yields:
        A configured FlociOCIService instance.
    """
    with provide_floci_container(
        container_service,
        image=floci_oci_image,
        name="floci_oci",
        container_port=FLOCI_CONTAINER_PORTS["oci"],
        health_path=FLOCI_HEALTH_PATHS["oci"],
        isolation_level=xdist_floci_isolation_level,
    ) as service:
        yield FlociOCIService(
            container=service.container,
            host=service.host,
            port=service.port,
            endpoint_url=f"http://{service.host}:{service.port}",
            resource_prefix=floci_resource_prefix,
            namespace=floci_oci_namespace,
            region=floci_oci_region,
            compartment_id=floci_oci_compartment_id,
        )


@pytest.fixture(scope="session")
def floci_aws_image() -> str:
    """Provide the Floci AWS emulator container image."""
    return os.getenv("FLOCI_AWS_IMAGE", DEFAULT_FLOCI_AWS_IMAGE)


@pytest.fixture(scope="session")
def floci_aws_region() -> str:
    """Provide the default AWS region for the Floci AWS emulator."""
    return os.getenv("FLOCI_AWS_REGION", "us-east-1")


@pytest.fixture(scope="session")
def floci_aws_access_key() -> str:
    """Provide the test AWS access key ID for the Floci AWS emulator."""
    return os.getenv("FLOCI_AWS_ACCESS_KEY", "test")


@pytest.fixture(scope="session")
def floci_aws_secret_key() -> str:
    """Provide the test AWS secret access key for the Floci AWS emulator."""
    return os.getenv("FLOCI_AWS_SECRET_KEY", "test")


@pytest.fixture(scope="session")
def floci_aws_service(
    container_service: ContainerService,
    floci_aws_image: str,
    floci_aws_region: str,
    floci_aws_access_key: str,
    floci_aws_secret_key: str,
    floci_resource_prefix: str,
    xdist_floci_isolation_level: XdistIsolationLevel,
) -> Generator[FlociAWSService, None, None]:
    """Start and yield a ready Floci AWS emulator service container.

    Yields:
        A configured FlociAWSService instance.
    """
    with provide_floci_container(
        container_service,
        image=floci_aws_image,
        name="floci_aws",
        container_port=FLOCI_CONTAINER_PORTS["aws"],
        health_path=FLOCI_HEALTH_PATHS["aws"],
        isolation_level=xdist_floci_isolation_level,
    ) as service:
        yield FlociAWSService(
            container=service.container,
            host=service.host,
            port=service.port,
            endpoint_url=f"http://{service.host}:{service.port}",
            resource_prefix=floci_resource_prefix,
            region=floci_aws_region,
            access_key=floci_aws_access_key,
            secret_key=floci_aws_secret_key,
        )


@pytest.fixture(scope="session")
def floci_az_image() -> str:
    """Provide the Floci Azure emulator container image."""
    return os.getenv("FLOCI_AZ_IMAGE", DEFAULT_FLOCI_AZ_IMAGE)


@pytest.fixture(scope="session")
def floci_az_account_name() -> str:
    """Provide the default Azure storage account name for the Floci Azure emulator."""
    return os.getenv("FLOCI_AZ_ACCOUNT_NAME", _AZURITE_DEFAULT_ACCOUNT)


@pytest.fixture(scope="session")
def floci_az_account_key() -> str:
    """Provide the default Azure storage account key for the Floci Azure emulator."""
    return os.getenv("FLOCI_AZ_ACCOUNT_KEY", _AZURITE_DEFAULT_KEY)


@pytest.fixture(scope="session")
def floci_az_service(
    container_service: ContainerService,
    floci_az_image: str,
    floci_az_account_name: str,
    floci_az_account_key: str,
    floci_resource_prefix: str,
    xdist_floci_isolation_level: XdistIsolationLevel,
) -> Generator[FlociAzureService, None, None]:
    """Start and yield a ready Floci Azure emulator service container.

    Yields:
        A configured FlociAzureService instance.
    """
    with provide_floci_container(
        container_service,
        image=floci_az_image,
        name="floci_az",
        container_port=FLOCI_CONTAINER_PORTS["azure"],
        health_path=FLOCI_HEALTH_PATHS["azure"],
        isolation_level=xdist_floci_isolation_level,
    ) as service:
        yield FlociAzureService(
            container=service.container,
            host=service.host,
            port=service.port,
            endpoint_url=f"http://{service.host}:{service.port}",
            resource_prefix=floci_resource_prefix,
            account_name=floci_az_account_name,
            account_key=floci_az_account_key,
        )


def _post_json(url: str, payload: dict[str, Any], *, existing: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST a JSON document and return the JSON object response, or ``existing`` on HTTP 409."""
    status, body = http_request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    if status == 409:
        return existing
    if status >= 400:
        raise urllib.error.HTTPError(url, status, f"HTTP {status}", email.message.Message(), io.BytesIO(body))
    parsed = json.loads(body) if body.strip() else None
    return parsed if isinstance(parsed, dict) else existing


def _is_floci_ready(service: ServiceContainer, *, health_path: str) -> bool:
    """Return ``True`` when the Floci health endpoint answers with a JSON object."""
    return check_floci_health(service.host, service.port, health_path) is not None


def _augment_list_bucket_xml(body: bytes) -> bytes:
    """Inject missing ``<ETag>`` and ``<LastModified>`` elements into S3 ``ListBucketResult`` XML ``<Contents>``."""
    if b"ListBucketResult" not in body:
        return body

    state: dict[str, Any] = {
        "in_contents": False,
        "prefix": "",
        "has_etag": False,
        "has_last_modified": False,
        "capture_key": False,
        "key_parts": [],
    }
    insertions: list[tuple[int, bytes]] = []
    parser = xml.parsers.expat.ParserCreate()

    def start_element(name: str, _attrs: dict[str, str]) -> None:
        prefix, sep, local = name.rpartition(":")
        elem_prefix = f"{prefix}{sep}"
        if local == "Contents":
            state["in_contents"] = True
            state["prefix"] = elem_prefix
            state["has_etag"] = False
            state["has_last_modified"] = False
            state["capture_key"] = False
            state["key_parts"] = []
            return
        if not state["in_contents"]:
            return
        if local == "ETag":
            state["has_etag"] = True
        elif local == "LastModified":
            state["has_last_modified"] = True
        elif local == "Key":
            state["capture_key"] = True

    def char_data(data: str) -> None:
        if state["in_contents"] and state["capture_key"]:
            state["key_parts"].append(data)

    def end_element(name: str) -> None:
        _, _, local = name.rpartition(":")
        if not state["in_contents"]:
            return
        if local == "Key":
            state["capture_key"] = False
            return
        if local == "Contents":
            chunks: list[bytes] = []
            elem_prefix = str(state["prefix"])
            if not state["has_etag"]:
                key_bytes = "".join(state["key_parts"]).encode("utf-8")
                etag_hex = hashlib.md5(key_bytes, usedforsecurity=False).hexdigest()
                chunks.append(f"<{elem_prefix}ETag>&quot;{etag_hex}&quot;</{elem_prefix}ETag>".encode())
            if not state["has_last_modified"]:
                iso_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                chunks.append(f"<{elem_prefix}LastModified>{iso_ts}</{elem_prefix}LastModified>".encode())
            if chunks:
                insertions.append((parser.CurrentByteIndex, b"".join(chunks)))
            state["in_contents"] = False
            state["capture_key"] = False

    parser.StartElementHandler = start_element
    parser.CharacterDataHandler = char_data
    parser.EndElementHandler = end_element
    try:
        parser.Parse(body, True)
    except xml.parsers.expat.ExpatError:
        return body
    if not insertions:
        return body
    mutable = bytearray(body)
    for offset, insertion in reversed(insertions):
        mutable[offset:offset] = insertion
    return bytes(mutable)


def _format_etag_from_body(body: bytes) -> str:
    return f'"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'


def _normalize_copy_etag(payload: Any, fallback_body: bytes) -> str:
    if isinstance(payload, dict):
        raw_etag = payload.get("etag") or payload.get("md5Hash")
        if isinstance(raw_etag, str) and raw_etag:
            stripped = raw_etag.strip('"')
            return f'"{stripped}"'
    return _format_etag_from_body(fallback_body)


class _FlociGCPCompatHTTPServer(http.server.ThreadingHTTPServer):
    """Daemon loopback server fronting a Floci GCP container."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, upstream_host: str, upstream_port: int) -> None:
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        super().__init__(("127.0.0.1", 0), _FlociGCPCompatHandler)


class _FlociGCPCompatHandler(http.server.BaseHTTPRequestHandler):
    """HTTP compatibility handler translating GCS XML HEAD, copy, and listing metadata."""

    def do_GET(self) -> None:
        """Forward a GET request and normalize 2xx headers/XML metadata."""
        self._handle_standard_request()

    def do_POST(self) -> None:
        """Forward a POST request."""
        self._handle_standard_request()

    def do_PUT(self) -> None:
        """Translate ``x-goog-copy-source`` PUTs to JSON ``copyTo``, or forward regular PUTs."""
        copy_source = next(
            (value for key, value in self.headers.items() if key.lower() == "x-goog-copy-source"),
            None,
        )
        if copy_source is not None:
            self._handle_xml_copy(copy_source)
            return
        self._handle_standard_request()

    def do_DELETE(self) -> None:
        """Forward a DELETE request."""
        self._handle_standard_request()

    def do_PATCH(self) -> None:
        """Forward a PATCH request."""
        self._handle_standard_request()

    def do_HEAD(self) -> None:
        """Serve XML/REST HEAD requests via upstream GET with exact Content-Length and empty body."""
        self._handle_head_via_get()

    def do_OPTIONS(self) -> None:
        """Forward an OPTIONS request."""
        self._handle_standard_request()

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Suppress HTTP access logging during test runs."""
        _ = (self.command, code, size)

    def _get_server(self) -> _FlociGCPCompatHTTPServer:
        server = self.server
        if not isinstance(server, _FlociGCPCompatHTTPServer):
            msg = f"Unexpected server type: {type(server).__name__}"
            raise TypeError(msg)
        return server

    def _forward_headers(self) -> dict[str, str]:
        return {key: value for key, value in self.headers.items() if key.lower() not in _HOP_BY_HOP_REQUEST_HEADERS}

    def _read_request_body(self) -> bytes:
        return read_http_handler_body(self.headers, self.rfile)

    def _is_xml_bucket_listing_request(self, body: bytes) -> bool:
        if self.command != "GET":
            return False
        path = urllib.parse.urlsplit(self.path).path.strip("/")
        if not path or "/" in path:
            return False
        trimmed = body.lstrip()
        return trimmed.startswith((b"<?xml", b"<ListBucketResult"))

    def _send_upstream_failure(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _write_normalized_response(
        self,
        status: int,
        upstream_headers: dict[str, str],
        body: bytes,
        *,
        is_head: bool = False,
    ) -> None:
        final_body = body
        if not is_head and 200 <= status < 300 and self._is_xml_bucket_listing_request(final_body):
            final_body = _augment_list_bucket_xml(final_body)
        headers_out: list[tuple[str, str]] = [
            (key, value) for key, value in upstream_headers.items() if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS
        ]
        if 200 <= status < 300:
            lower_keys = {key.lower() for key, _ in headers_out}
            if "etag" not in lower_keys:
                headers_out.append(("ETag", _format_etag_from_body(final_body)))
            if "last-modified" not in lower_keys:
                headers_out.append(("Last-Modified", email.utils.formatdate(usegmt=True)))
        self.send_response(status)
        for key, value in headers_out:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(final_body)))
        self.end_headers()
        if not is_head and final_body:
            self.wfile.write(final_body)

    def _handle_head_via_get(self) -> None:
        server = self._get_server()
        upstream_url = f"http://{server.upstream_host}:{server.upstream_port}{self.path}"
        req = urllib.request.Request(upstream_url, headers=self._forward_headers(), method="GET")
        try:
            status, resp_headers, resp_body = send_http_request(req, timeout=30.0)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            self._send_upstream_failure(502, str(exc))
            return
        self._write_normalized_response(status, resp_headers, resp_body, is_head=True)

    def _parse_copy_coordinates(self, copy_source: str) -> tuple[str, str, str, str] | None:
        src_clean = copy_source.split("?", 1)[0].lstrip("/")
        if "/" not in src_clean:
            self._send_upstream_failure(400, f"Invalid x-goog-copy-source header: {copy_source!r}")
            return None
        dst_clean = urllib.parse.urlsplit(self.path).path.lstrip("/")
        if "/" not in dst_clean:
            self._send_upstream_failure(400, f"Invalid copy destination path: {self.path!r}")
            return None
        raw_src_b, raw_src_k = src_clean.split("/", 1)
        raw_dst_b, raw_dst_k = dst_clean.split("/", 1)
        coords = (
            urllib.parse.unquote(raw_src_b),
            urllib.parse.unquote(raw_src_k),
            urllib.parse.unquote(raw_dst_b),
            urllib.parse.unquote(raw_dst_k),
        )
        if not all(coords):
            self._send_upstream_failure(400, "Copy source and destination buckets and object keys must be non-empty")
            return None
        return coords

    def _handle_xml_copy(self, copy_source: str) -> None:
        coords = self._parse_copy_coordinates(copy_source)
        if coords is None:
            return
        src_b, src_k, dst_b, dst_k = coords
        server = self._get_server()
        copy_url = (
            f"http://{server.upstream_host}:{server.upstream_port}/storage/v1/b/"
            f"{urllib.parse.quote(src_b, safe='')}/o/{urllib.parse.quote(src_k, safe='')}/copyTo/"
            f"b/{urllib.parse.quote(dst_b, safe='')}/o/{urllib.parse.quote(dst_k, safe='')}"
        )
        req = urllib.request.Request(
            copy_url,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            status, resp_headers, resp_body = send_http_request(req, timeout=30.0)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            self._send_upstream_failure(502, str(exc))
            return
        if status >= 400:
            self._write_normalized_response(status, resp_headers, resp_body)
            return
        try:
            parsed = json.loads(resp_body.decode("utf-8")) if resp_body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        etag = _normalize_copy_etag(parsed, resp_body)
        iso_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        xml_body = (
            f"<CopyObjectResult><LastModified>{iso_ts}</LastModified>"
            f"<ETag>{html.escape(etag, quote=True)}</ETag></CopyObjectResult>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", email.utils.formatdate(usegmt=True))
        self.send_header("Content-Length", str(len(xml_body)))
        self.end_headers()
        self.wfile.write(xml_body)

    def _handle_standard_request(self) -> None:
        server = self._get_server()
        try:
            raw_body = self._read_request_body()
        except ValueError as exc:
            self._send_upstream_failure(400, f"Invalid HTTP request body: {exc}")
            return
        upstream_url = f"http://{server.upstream_host}:{server.upstream_port}{self.path}"
        outgoing_headers = self._forward_headers()
        if raw_body or self.command in {"POST", "PUT", "PATCH"}:
            outgoing_headers["Content-Length"] = str(len(raw_body))
        request_data = raw_body if raw_body or self.command in {"POST", "PUT", "PATCH"} else None
        req = urllib.request.Request(upstream_url, data=request_data, headers=outgoing_headers, method=self.command)
        try:
            status, resp_headers, resp_body = send_http_request(req, timeout=30.0)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            self._send_upstream_failure(502, str(exc))
            return
        self._write_normalized_response(status, resp_headers, resp_body)


@contextmanager
def _start_floci_gcp_compat_proxy(upstream_host: str, upstream_port: int) -> Generator[tuple[str, int], None, None]:
    """Start the ephemeral loopback compatibility proxy fronting a Floci GCP container.

    Yields:
        Tuple of ``(host, port)`` for the bound loopback proxy socket.
    """
    server = _FlociGCPCompatHTTPServer(upstream_host, upstream_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
