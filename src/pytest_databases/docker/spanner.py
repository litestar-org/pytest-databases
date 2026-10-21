from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel


SPANNER_GCLOUD_CLI_IMAGE = "gcr.io/google.com/cloudsdktool/cloud-sdk:slim"


def _send_spanner_request_with_retry(
    url: str,
    payload: dict[str, Any],
    max_attempts: int = 10,
) -> None:
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


def bootstrap_spanner_emulator(
    target_or_service: Any,
    rest_port_or_container: Any = None,
    *,
    project: str,
    instance_name: str,
    database_name: str,
) -> None:
    if isinstance(target_or_service, str) and isinstance(rest_port_or_container, int):
        host = target_or_service
        rest_port = rest_port_or_container
    else:
        container = rest_port_or_container
        host = "127.0.0.1"
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


_bootstrap_spanner_emulator = bootstrap_spanner_emulator


@pytest.fixture(scope="session")
def xdist_spanner_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def spanner_project() -> str:
    return "emulator-test-project"


@pytest.fixture(scope="session")
def spanner_instance_name() -> str:
    return "emulator-test-instance"


@pytest.fixture(scope="session")
def spanner_database_name() -> str:
    return "emulator-test-database"


@pytest.fixture(scope="session")
def spanner_image() -> str:
    return "gcr.io/cloud-spanner-emulator/emulator:latest"


@dataclass
class SpannerService(ServiceContainer):
    project: str
    database_name: str
    instance_name: str
    rest_port: int = 0

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def rest_endpoint(self) -> str:
        return f"{self.host}:{self.rest_port}"


@pytest.fixture(autouse=False, scope="session")
def spanner_service(
    docker_service: DockerService,
    xdist_spanner_isolation_level: XdistIsolationLevel,
    spanner_image: str,
    spanner_project: str,
    spanner_instance_name: str,
    spanner_database_name: str,
) -> Generator[SpannerService, None, None]:
    worker_num = get_xdist_worker_num()
    name = "spanner"
    effective_db = spanner_database_name
    if worker_num is not None:
        if xdist_spanner_isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            effective_db = f"{spanner_database_name}_{worker_num}"

    with docker_service.run(
        image=spanner_image,
        name=name,
        container_port=9010,
        extra_ports={9020: None},
        wait_for_log="gRPC server listening at",
        transient=worker_num is not None and xdist_spanner_isolation_level == "server",
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
