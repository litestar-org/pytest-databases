"""Floci multi-cloud (GCP, OCI, AWS, Azure) emulator container fixtures and stdlib HTTP helpers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_id, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

__all__ = [
    "DEFAULT_FLOCI_AWS_IMAGE",
    "DEFAULT_FLOCI_AZ_IMAGE",
    "DEFAULT_FLOCI_GCP_IMAGE",
    "DEFAULT_FLOCI_OCI_IMAGE",
    "FLOCI_GATEWAY_PORT",
    "FlociAWSService",
    "FlociAzureService",
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
    "floci_gcp_image",
    "floci_gcp_project",
    "floci_gcp_service",
    "floci_oci_compartment_id",
    "floci_oci_image",
    "floci_oci_namespace",
    "floci_oci_region",
    "floci_oci_service",
    "floci_resource_prefix",
    "floci_service",
    "gcs_service",
    "provide_floci_container",
    "xdist_floci_isolation_level",
]

FLOCI_GATEWAY_PORT = 4566
DEFAULT_FLOCI_GCP_IMAGE = "floci/floci-gcp:latest"
DEFAULT_FLOCI_OCI_IMAGE = "floci/floci-oci:latest"
DEFAULT_FLOCI_AWS_IMAGE = "floci/floci:latest"
DEFAULT_FLOCI_AZ_IMAGE = "floci/floci-az:latest"
_AZURITE_DEFAULT_ACCOUNT = "devstoreaccount1"
_AZURITE_DEFAULT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


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
    """Connection metadata and helpers for a Floci OCI emulator (Object Storage, Queue, Vault, Secrets, NoSQL, Streaming)."""

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
    """Connection metadata for a Floci AWS emulator (S3, SQS, SNS, DynamoDB, Secrets Manager, KMS, Lambda)."""

    region: str
    access_key: str
    secret_key: str


@dataclass
class FlociAzureService(FlociService):
    """Connection metadata for a Floci Azure emulator (Blob Storage, Queue Storage, Service Bus, Key Vault, Cosmos DB)."""

    account_name: str
    account_key: str

    @property
    def blob_endpoint(self) -> str:
        """The path-style Azure Blob Storage endpoint URL."""
        return f"{self.endpoint_url}/{self.account_name}"


def check_floci_health(host: str, port: int, *, timeout: float = 2.0) -> dict[str, Any] | None:
    """Probe the Floci HTTP gateway health endpoint using stdlib ``urllib.request``.

    Args:
        host: Mapped container host address.
        port: Mapped container gateway port.
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed health JSON payload if healthy (HTTP 200), otherwise ``None``.
    """
    for path in ("/_floci/health", "/_localstack/health"):
        url = f"http://{host}:{port}{path}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    continue
                raw = response.read().decode("utf-8", errors="replace")
                return _parse_health_payload(raw)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
    return None


def ensure_gcs_bucket(
    host: str,
    port: int,
    bucket_name: str,
    *,
    project: str = "pytest-databases",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Create a Google Cloud Storage bucket on a Floci GCP emulator via stdlib HTTP.

    Args:
        host: Mapped container host address.
        port: Mapped container gateway port.
        bucket_name: Name of the GCS bucket to create.
        project: GCP project ID.
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed bucket metadata dictionary.
    """
    encoded_project = urllib.parse.quote(project, safe="")
    url = f"http://{host}:{port}/storage/v1/b?project={encoded_project}"
    payload = json.dumps({"name": bucket_name}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body.strip() else {"name": bucket_name}
            return parsed if isinstance(parsed, dict) else {"name": bucket_name}
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return {"name": bucket_name, "project": project}
        raise


def ensure_oci_bucket(
    host: str,
    port: int,
    namespace: str,
    bucket_name: str,
    *,
    compartment_id: str = "ocid1.compartment.oc1..pytest",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Create an Oracle Cloud Infrastructure Object Storage bucket on a Floci OCI emulator via stdlib HTTP.

    Args:
        host: Mapped container host address.
        port: Mapped container gateway port.
        namespace: OCI Object Storage namespace.
        bucket_name: Name of the OCI bucket to create.
        compartment_id: OCI compartment OCID.
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed bucket metadata dictionary.
    """
    encoded_ns = urllib.parse.quote(namespace, safe="")
    url = f"http://{host}:{port}/n/{encoded_ns}/b/"
    payload = json.dumps({"name": bucket_name, "compartmentId": compartment_id}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body.strip() else {"name": bucket_name, "namespace": namespace}
            return parsed if isinstance(parsed, dict) else {"name": bucket_name, "namespace": namespace}
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return {"name": bucket_name, "namespace": namespace}
        raise


@contextmanager
def provide_floci_container(
    container_service: ContainerService,
    *,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel = "database",
) -> Generator[ServiceContainer, None, None]:
    """Start and yield a ready Floci gateway container on port 4566.

    Yields:
        A ready ServiceContainer instance.
    """
    worker_num = get_xdist_worker_num()
    container_name = f"{name}_{worker_num}" if worker_num is not None and isolation_level == "server" else name
    transient = worker_num is not None and isolation_level == "server"

    with container_service.run(
        image=image,
        name=container_name,
        container_port=FLOCI_GATEWAY_PORT,
        check=_is_floci_ready,
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
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return "pytest-databases"
    return f"pytest-databases-{worker_id}"


@pytest.fixture(scope="session")
def floci_gcp_service(
    container_service: ContainerService,
    floci_gcp_image: str,
    floci_gcp_project: str,
    floci_resource_prefix: str,
    xdist_floci_isolation_level: XdistIsolationLevel,
) -> Generator[FlociGCPService, None, None]:
    """Start and yield a ready Floci GCP emulator service container.

    Yields:
        A configured FlociGCPService instance.
    """
    with provide_floci_container(
        container_service,
        image=floci_gcp_image,
        name="floci_gcp",
        isolation_level=xdist_floci_isolation_level,
    ) as service:
        yield FlociGCPService(
            container=service.container,
            host=service.host,
            port=service.port,
            endpoint_url=f"http://{service.host}:{service.port}",
            resource_prefix=floci_resource_prefix,
            project=floci_gcp_project,
        )


@pytest.fixture(scope="session")
def gcs_service(floci_gcp_service: FlociGCPService) -> FlociGCPService:
    """Alias for ``floci_gcp_service`` providing a clientless Google Cloud Storage emulator."""
    return floci_gcp_service


@pytest.fixture(scope="session")
def floci_oci_image() -> str:
    """Provide the Floci OCI emulator container image."""
    return os.getenv("FLOCI_OCI_IMAGE", DEFAULT_FLOCI_OCI_IMAGE)


@pytest.fixture(scope="session")
def floci_oci_namespace() -> str:
    """Provide a worker-scoped OCI Object Storage namespace."""
    if value := os.getenv("FLOCI_OCI_NAMESPACE"):
        return value
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return "pytestns"
    return f"pytestns-{worker_id}"


@pytest.fixture(scope="session")
def floci_oci_region() -> str:
    """Provide the default OCI region for the Floci OCI emulator."""
    return os.getenv("FLOCI_OCI_REGION", "us-ashburn-1")


@pytest.fixture(scope="session")
def floci_oci_compartment_id() -> str:
    """Provide the default OCI compartment OCID for the Floci OCI emulator."""
    return os.getenv("FLOCI_OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..pytest")


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
def floci_service(floci_aws_service: FlociAWSService) -> FlociAWSService:
    """Alias for ``floci_aws_service``."""
    return floci_aws_service


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


def _parse_health_payload(raw: str) -> dict[str, Any]:
    """Parse a Floci or LocalStack JSON health payload."""
    if not raw.strip():
        return {"status": "running"}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"status": "running"}


def _is_floci_ready(service: ServiceContainer) -> bool:
    """Return ``True`` when the Floci gateway health endpoint responds."""
    return check_floci_health(service.host, service.port) is not None
