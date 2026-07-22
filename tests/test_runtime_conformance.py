from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from docker.errors import NotFound

from pytest_databases import ContainerService, ResolvedRuntime, RuntimeType

if TYPE_CHECKING:
    from docker import DockerClient

pytestmark = [
    pytest.mark.runtime_conformance,
    pytest.mark.skipif(
        os.environ.get("PYTEST_DATABASES_CONFORMANCE") != "1",
        reason="set PYTEST_DATABASES_CONFORMANCE=1 to exercise a real container API",
    ),
]


def test_resolved_runtime_matches_explicit_engine(resolved_container_runtime: ResolvedRuntime) -> None:
    expected = RuntimeType(os.environ["PYTEST_DATABASES_CONTAINER_RUNTIME"])
    assert resolved_container_runtime.kind is expected


def test_managed_container_lifecycle_conforms(
    container_client: DockerClient,
    container_service: ContainerService,
) -> None:
    with container_service.run(
        "busybox:latest",
        8080,
        "runtime-conformance",
        command=["sh", "-c", "echo runtime-ready; sleep 30"],
        wait_for_log="runtime-ready",
        timeout=20,
        transient=True,
    ) as service:
        container_id = service.container.id
        assert container_id is not None
        assert service.container.labels["pytest_databases.owner"] == container_service.owner_id
        assert service.container.exec_run(["sh", "-c", "printf conformance"]).output == b"conformance"
        assert b"runtime-ready" in service.container.logs()
        assert service.port > 0

    with pytest.raises(NotFound):
        container_client.containers.get(container_id)


def test_host_and_container_namespace_sidecars_conform(container_service: ContainerService) -> None:
    host_output = container_service.run_container(
        "busybox:latest",
        service_name="host-network-conformance",
        command=["sh", "-c", "printf host-network"],
        network_mode="host",
        remove=True,
    )
    assert host_output == b"host-network"

    with container_service.run(
        "busybox:latest",
        8081,
        "namespace-conformance",
        command=["sh", "-c", "echo namespace-ready; sleep 30"],
        wait_for_log="namespace-ready",
        timeout=20,
        transient=True,
    ) as service:
        namespace_output = container_service.run_container(
            "busybox:latest",
            service_name="container-network-conformance",
            command=["sh", "-c", "printf container-network"],
            network_mode=f"container:{service.container.id}",
            remove=True,
        )
        assert namespace_output == b"container-network"
