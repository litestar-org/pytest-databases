from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest
from docker.errors import NotFound

from pytest_databases import ContainerService, ResolvedRuntime, RuntimeType

if TYPE_CHECKING:
    from pathlib import Path

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


def test_overlapping_pytest_sessions_do_not_reuse_or_delete_each_other(
    container_client: DockerClient,
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "test_overlap.py"
    test_file.write_text(
        """
import os
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("worker_case", [0, 1])
def test_hold(container_service, worker_case):
    session = os.environ["OVERLAP_SESSION"]
    shared = Path(os.environ["OVERLAP_DIRECTORY"])
    with container_service.run(
        "busybox:latest",
        8090,
        "overlap",
        command=["sh", "-c", "echo overlap-ready; sleep 60"],
        wait_for_log="overlap-ready",
        timeout=20,
    ) as service:
        (shared / f"{session}-{worker_case}.id").write_text(service.container.id, encoding="utf-8")
        if session == "a":
            deadline = time.time() + 30
            while not (shared / "release-a").exists() and time.time() < deadline:
                time.sleep(0.1)
""",
        encoding="utf-8",
    )

    def start(session: str) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.update({"OVERLAP_SESSION": session, "OVERLAP_DIRECTORY": str(tmp_path)})
        return subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-n", "2", str(test_file), "--basetemp", str(tmp_path / session)],
            cwd=tmp_path,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def wait_for(path: Path) -> None:
        deadline = time.time() + 30
        while not path.exists() and time.time() < deadline:
            time.sleep(0.1)
        assert path.exists()

    first = start("a")
    second: subprocess.Popen[str] | None = None

    def verify_overlap() -> str:
        nonlocal second
        first_paths = [tmp_path / f"a-{case}.id" for case in (0, 1)]
        for path in first_paths:
            wait_for(path)
        first_ids = {path.read_text(encoding="utf-8") for path in first_paths}
        assert len(first_ids) == 1
        first_container_id = first_ids.pop()
        second = start("b")
        second_paths = [tmp_path / f"b-{case}.id" for case in (0, 1)]
        for path in second_paths:
            wait_for(path)
        second_ids = {path.read_text(encoding="utf-8") for path in second_paths}
        assert len(second_ids) == 1
        assert first_container_id not in second_ids
        second_output, _ = second.communicate(timeout=30)
        assert second.returncode == 0, second_output
        container_client.containers.get(first_container_id).reload()
        return first_container_id

    first_id = ""
    first_output = ""
    try:
        first_id = verify_overlap()
    finally:
        (tmp_path / "release-a").touch()
        first_output, _ = first.communicate(timeout=30)
        if second is not None and second.poll() is None:
            second.terminate()
            second.communicate(timeout=10)
    assert first.returncode == 0, first_output

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            container_client.containers.get(first_id)
        except NotFound:
            break
        time.sleep(0.1)
    else:
        pytest.fail("first pytest session did not remove its owned container")
