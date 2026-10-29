"""Google Cloud Spanner emulator container fixtures and HTTP REST provisioning."""

from __future__ import annotations

import contextlib
import importlib
import json
import time
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "SpannerService",
    "bootstrap_spanner_emulator",
    "provide_spanner_service",
    "spanner_connection",
    "spanner_database_name",
    "spanner_image",
    "spanner_instance_name",
    "spanner_project",
    "spanner_service",
    "xdist_spanner_isolation_level",
]


@dataclass
class SpannerService(ServiceContainer):
    """Container handle with gRPC and REST endpoints for Cloud Spanner emulator."""

    project: str
    database_name: str
    instance_name: str
    rest_port: int = 0

    @property
    def endpoint(self) -> str:
        """GRPC endpoint for Cloud Spanner client connections."""
        return f"{self.host}:{self.port}"

    @property
    def rest_endpoint(self) -> str:
        """HTTP REST endpoint for Cloud Spanner administration."""
        return f"{self.host}:{self.rest_port}"

    @property
    def credentials(self) -> Any:
        """Deprecated AnonymousCredentials for Cloud Spanner emulator."""
        warnings.warn(
            "'SpannerService.credentials' is deprecated and will be removed in a future release. "
            "Instantiate 'google.auth.credentials.AnonymousCredentials()' directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        credentials_mod = importlib.import_module("google.auth.credentials")
        return credentials_mod.AnonymousCredentials()

    @property
    def client_options(self) -> Any:
        """Deprecated ClientOptions for Cloud Spanner emulator."""
        warnings.warn(
            "'SpannerService.client_options' is deprecated and will be removed in a future release. "
            "Instantiate 'google.api_core.client_options.ClientOptions(api_endpoint=service.endpoint)' directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        options_mod = importlib.import_module("google.api_core.client_options")
        return options_mod.ClientOptions(api_endpoint=self.endpoint)


def bootstrap_spanner_emulator(
    target_or_service: Any,
    rest_port_or_container: Any = None,
    *,
    project: str,
    instance_name: str,
    database_name: str,
) -> None:
    """Provision Spanner emulator instance and database via native HTTP REST port 9020.

    Args:
        target_or_service: Host string or service instance.
        rest_port_or_container: REST port integer or container instance.
        project: Google Cloud project identifier.
        instance_name: Spanner instance identifier.
        database_name: Spanner database identifier.
    """
    if isinstance(target_or_service, str) and isinstance(rest_port_or_container, int):
        host = target_or_service
        rest_port = rest_port_or_container
    elif isinstance(target_or_service, SpannerService):
        host = target_or_service.host
        rest_port = target_or_service.rest_port or 9020
    else:
        container = (
            target_or_service.container if isinstance(target_or_service, ServiceContainer) else rest_port_or_container
        )
        host = target_or_service.host if isinstance(target_or_service, ServiceContainer) else "127.0.0.1"
        binding = container.ports.get("9020/tcp") if container and hasattr(container, "ports") else None
        rest_port = int(binding[0]["HostPort"]) if binding else 9020

    instance_url = f"http://{host}:{rest_port}/v1/projects/{project}/instances"
    instance_payload = {
        "instanceId": instance_name,
        "instance": {
            "config": f"projects/{project}/instanceConfigs/emulator-config",
            "displayName": "pytest-databases",
            "nodeCount": 1,
        },
    }
    database_url = f"http://{host}:{rest_port}/v1/projects/{project}/instances/{instance_name}/databases"
    database_payload = {
        "createStatement": f"CREATE DATABASE `{database_name}`",
    }
    _send_spanner_request_with_retry(instance_url, instance_payload)
    _send_spanner_request_with_retry(database_url, database_payload)


@contextlib.contextmanager
def provide_spanner_service(
    docker_service: DockerService,
    spanner_image: str,
    spanner_project: str,
    spanner_instance_name: str,
    spanner_database_name: str,
    isolation_level: XdistIsolationLevel = "database",
) -> Generator[SpannerService, None, None]:
    """Start and manage a Google Cloud Spanner emulator container.

    Args:
        docker_service: The container service manager.
        spanner_image: Container image for the emulator.
        spanner_project: Project identifier.
        spanner_instance_name: Instance identifier.
        spanner_database_name: Database identifier.
        isolation_level: Isolation level for xdist workers (database or server).

    Yields:
        A SpannerService handle with host and port bindings.
    """
    worker_num = get_xdist_worker_num()
    name = "spanner"
    effective_db = spanner_database_name
    if worker_num is not None:
        if isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            effective_db = f"{spanner_database_name}_{worker_num}"

    with docker_service.run(
        image=spanner_image,
        name=name,
        container_port=9010,
        extra_ports={9020: None},
        wait_for_log="gRPC server listening at",
        transient=worker_num is not None and isolation_level == "server",
    ) as service:
        rest_port = docker_service.resolve_port(service.container, 9020)
        bootstrap_spanner_emulator(
            service.host,
            rest_port,
            project=spanner_project,
            instance_name=spanner_instance_name,
            database_name=effective_db,
        )
        yield SpannerService(
            host=service.host,
            port=service.port,
            container=service.container,
            project=spanner_project,
            instance_name=spanner_instance_name,
            database_name=effective_db,
            rest_port=rest_port,
        )


@pytest.fixture(scope="session")
def xdist_spanner_isolation_level() -> XdistIsolationLevel:
    """Determine Spanner xdist isolation mode (database or server)."""
    return "database"


@pytest.fixture(scope="session")
def spanner_project() -> str:
    """Project identifier for Cloud Spanner emulator."""
    return "emulator-test-project"


@pytest.fixture(scope="session")
def spanner_instance_name() -> str:
    """Instance identifier for Cloud Spanner emulator."""
    return "emulator-test-instance"


@pytest.fixture(scope="session")
def spanner_database_name() -> str:
    """Database identifier for Cloud Spanner emulator."""
    return "emulator-test-database"


@pytest.fixture(scope="session")
def spanner_image() -> str:
    """Container image for Cloud Spanner emulator."""
    return "gcr.io/cloud-spanner-emulator/emulator:latest"


@pytest.fixture(autouse=False, scope="session")
def spanner_service(
    docker_service: DockerService,
    xdist_spanner_isolation_level: XdistIsolationLevel,
    spanner_image: str,
    spanner_project: str,
    spanner_instance_name: str,
    spanner_database_name: str,
) -> Generator[SpannerService, None, None]:
    """Start and manage a Google Cloud Spanner emulator container.

    Yields:
        A SpannerService handle with host and port bindings.
    """
    with provide_spanner_service(
        docker_service=docker_service,
        spanner_image=spanner_image,
        spanner_project=spanner_project,
        spanner_instance_name=spanner_instance_name,
        spanner_database_name=spanner_database_name,
        isolation_level=xdist_spanner_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def spanner_connection(
    spanner_service: SpannerService,
) -> Generator[Any, None, None]:
    """Provide a deprecated Cloud Spanner client connected to the emulator.

    Yields:
        Active google.cloud.spanner.Client instance.
    """
    warnings.warn(
        "'spanner_connection' is deprecated and will be removed in a future release. "
        "Use 'spanner_service' and instantiate your google.cloud.spanner.Client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    spanner = importlib.import_module("google.cloud.spanner")
    credentials_mod = importlib.import_module("google.auth.credentials")
    options_mod = importlib.import_module("google.api_core.client_options")
    client = spanner.Client(
        project=spanner_service.project,
        credentials=credentials_mod.AnonymousCredentials(),
        client_options=options_mod.ClientOptions(api_endpoint=spanner_service.endpoint),
    )
    try:
        yield client
    finally:
        client.close()


def _send_spanner_request_with_retry(
    url: str,
    payload: dict[str, Any],
    max_attempts: int = 10,
) -> None:
    """Send a JSON POST request to the Spanner REST API with retries for container readiness.

    Args:
        url: Target REST URL.
        payload: Request payload dictionary.
        max_attempts: Maximum retry attempts before raising.

    Raises:
        HTTPError: If the server returns an unexpected HTTP error code other than 409.
        URLError: If the connection fails after max attempts.
    """
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(max_attempts):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
                return
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return
            if attempt == max_attempts - 1:
                raise
        except (urllib.error.URLError, ConnectionError, OSError):
            if attempt == max_attempts - 1:
                raise
        time.sleep(0.5)
