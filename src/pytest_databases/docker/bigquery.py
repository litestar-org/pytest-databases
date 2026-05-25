from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@pytest.fixture(scope="session")
def xdist_bigquery_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def bigquery_image() -> str:
    return "ghcr.io/goccy/bigquery-emulator:latest"


@pytest.fixture(scope="session")
def platform() -> str:
    return "linux/x86_64"


@dataclass
class BigQueryService(ServiceContainer):
    project: str
    dataset: str

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"


def _query_bigquery_emulator(
    host: str,
    port: int,
    project: str,
    sql: str,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    body = json.dumps({"query": sql, "useLegacySql": False}).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}:{port}/bigquery/v2/projects/{project}/queries",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="session")
def bigquery_service(
    docker_service: DockerService,
    xdist_bigquery_isolation_level: XdistIsolationLevel,
    bigquery_image: str,
    platform: str,
) -> Generator[BigQueryService, None, None]:
    project = "emulator-test-project"
    dataset = "test-dataset"
    container_name = "bigquery"

    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        container_name += f"_{worker_num}"

    def check(_service: ServiceContainer) -> bool:
        try:
            payload = _query_bigquery_emulator(
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
            return payload["rows"][0]["f"][0]["v"] == "1"
        except (KeyError, IndexError, TypeError):
            return False

    with docker_service.run(
        image=bigquery_image,
        command=f"--project={project} --dataset={dataset}",
        name=container_name,
        check=check,
        env={
            "PROJECT_ID": project,
            "DATASET_NAME": dataset,
        },
        container_port=9050,
        timeout=60,
        transient=xdist_bigquery_isolation_level == "server",
        platform=platform,
    ) as service:
        yield BigQueryService(
            host=service.host,
            port=service.port,
            container=service.container,
            project=project,
            dataset=dataset,
        )
