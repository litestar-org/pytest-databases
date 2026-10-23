"""Floci multi-cloud (GCP, OCI, AWS, Azure) emulator container fixtures and stdlib HTTP helpers.

Each Floci image serves one cloud on its own gateway port and health path, listed in ``FLOCI_CONTAINER_PORTS`` and
``FLOCI_HEALTH_PATHS``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Literal

import pytest

from pytest_databases.helpers import get_xdist_worker_num, http_get_json
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
        container_port=FLOCI_CONTAINER_PORTS["gcp"],
        health_path=FLOCI_HEALTH_PATHS["gcp"],
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
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise
        exc.close()
        return existing
    parsed = json.loads(body) if body.strip() else None
    return parsed if isinstance(parsed, dict) else existing


def _is_floci_ready(service: ServiceContainer, *, health_path: str) -> bool:
    """Return ``True`` when the Floci health endpoint answers with a JSON object."""
    return check_floci_health(service.host, service.port, health_path) is not None
