"""Google BigQuery emulator container service fixtures."""

from __future__ import annotations

import importlib
import json
import urllib.error
import urllib.request
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService

__all__ = (
    "BigQueryService",
    "bigquery_client",
    "bigquery_image",
    "bigquery_service",
    "platform",
    "provide_bigquery_client",
    "provide_bigquery_service",
    "query_bigquery_emulator",
    "xdist_bigquery_isolation_level",
)


@dataclass
class BigQueryService(ServiceContainer):
    """Connection metadata for a Google BigQuery emulator container service."""

    project: str
    dataset: str

    @property
    def endpoint(self) -> str:
        """The HTTP API endpoint URL for the BigQuery emulator."""
        return f"http://{self.host}:{self.port}"

    @property
    def credentials(self) -> Any:
        """Deprecated ``AnonymousCredentials`` instance for the BigQuery emulator."""
        warnings.warn(
            "BigQueryService.credentials is deprecated and will be removed in a future release. "
            "Construct your own google.auth.credentials.AnonymousCredentials() instance.",
            DeprecationWarning,
            stacklevel=2,
        )
        creds_mod: Any = importlib.import_module("google.auth.credentials")
        return creds_mod.AnonymousCredentials()

    @property
    def client_options(self) -> Any:
        """Deprecated ``ClientOptions`` configured with the emulator API endpoint."""
        warnings.warn(
            "BigQueryService.client_options is deprecated and will be removed in a future release. "
            "Construct ClientOptions(api_endpoint=service.endpoint) directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        options_mod: Any = importlib.import_module("google.api_core.client_options")
        return options_mod.ClientOptions(api_endpoint=self.endpoint)


def query_bigquery_emulator(
    host: str,
    port: int,
    project: str,
    sql: str,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Execute a SQL query against the BigQuery emulator REST API using stdlib ``urllib.request``."""
    body = json.dumps({"query": sql, "useLegacySql": False}).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}:{port}/bigquery/v2/projects/{project}/queries",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return payload


@contextmanager
def provide_bigquery_service(
    docker_service: DockerService,
    isolation_level: XdistIsolationLevel,
    image: str,
    platform_arch: str,
) -> Generator[BigQueryService, None, None]:
    """Start and yield a BigQuery emulator service container.

    Args:
        docker_service: Docker service manager.
        isolation_level: xdist isolation mode.
        image: BigQuery emulator image name.
        platform_arch: Target container platform architecture.

    Yields:
        A running :class:`BigQueryService` instance.
    """
    project = "emulator-test-project"
    default_dataset = "test-dataset"
    dataset = default_dataset
    container_name = "bigquery"

    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        if isolation_level == "server":
            container_name += f"_{worker_num}"
        else:
            dataset = f"{default_dataset}_{worker_num}"

    def check(_service: ServiceContainer) -> bool:
        try:
            payload = query_bigquery_emulator(
                _service.host,
                _service.port,
                project,
                "SELECT 1 as one",
            )
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
            return False
        if payload.get("jobComplete") is not True:
            return False
        try:
            return bool(payload["rows"][0]["f"][0]["v"] == "1")
        except (KeyError, IndexError, TypeError):
            return False

    with docker_service.run(
        image=image,
        command=f"--project={project} --dataset={default_dataset}",
        name=container_name,
        check=check,
        env={
            "PROJECT_ID": project,
            "DATASET_NAME": default_dataset,
        },
        container_port=9050,
        timeout=60,
        transient=isolation_level == "server",
        platform=platform_arch,
    ) as service:
        if dataset != default_dataset:
            _ensure_bigquery_dataset(service.host, service.port, project, dataset)
        yield BigQueryService(
            host=service.host,
            port=service.port,
            container=service.container,
            project=project,
            dataset=dataset,
        )


@contextmanager
def provide_bigquery_client(bigquery_service: BigQueryService) -> Generator[Any, None, None]:
    """Emit a deprecation warning and yield a ``google.cloud.bigquery.Client`` instance.

    Yields:
        A configured ``bigquery.Client`` connected to ``bigquery_service``.
    """
    warnings.warn(
        "The 'bigquery_client' fixture is deprecated and will be removed in a future release. "
        "Use 'bigquery_service' and construct your own google.cloud.bigquery.Client.",
        DeprecationWarning,
        stacklevel=2,
    )
    bq_mod: Any = importlib.import_module("google.cloud.bigquery")
    options_mod: Any = importlib.import_module("google.api_core.client_options")
    creds_mod: Any = importlib.import_module("google.auth.credentials")
    yield bq_mod.Client(
        project=bigquery_service.project,
        client_options=options_mod.ClientOptions(api_endpoint=bigquery_service.endpoint),
        credentials=creds_mod.AnonymousCredentials(),
    )


@pytest.fixture(scope="session")
def xdist_bigquery_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for BigQuery."""
    return "database"


@pytest.fixture(scope="session")
def bigquery_image() -> str:
    """Return the default BigQuery emulator container image tag."""
    return "ghcr.io/goccy/bigquery-emulator:latest"


@pytest.fixture(scope="session")
def platform() -> str:
    """Return the container platform architecture for the BigQuery emulator."""
    return "linux/x86_64"


@pytest.fixture(scope="session")
def bigquery_service(
    docker_service: DockerService,
    xdist_bigquery_isolation_level: XdistIsolationLevel,
    bigquery_image: str,
    platform: str,
) -> Generator[BigQueryService, None, None]:
    """Provide a session-scoped BigQuery emulator service.

    Yields:
        A running :class:`BigQueryService` instance.
    """
    with provide_bigquery_service(
        docker_service,
        xdist_bigquery_isolation_level,
        bigquery_image,
        platform,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def bigquery_client(bigquery_service: BigQueryService) -> Generator[Any, None, None]:
    """Provide a deprecated ``google.cloud.bigquery.Client`` connected to the emulator.

    Yields:
        A configured ``bigquery.Client`` instance.
    """
    with provide_bigquery_client(bigquery_service) as client:
        yield client


def _ensure_bigquery_dataset(host: str, port: int, project: str, dataset: str, *, timeout: float = 5.0) -> None:
    body = json.dumps({"datasetReference": {"projectId": project, "datasetId": dataset}}).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}:{port}/bigquery/v2/projects/{project}/datasets",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return
        raise
