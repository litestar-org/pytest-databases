from __future__ import annotations

# ruff: noqa: PLC2701
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

from pytest_databases import ContainerService as PublicContainerService
from pytest_databases import DockerService as PublicDockerService
from pytest_databases._service import (
    ContainerService,
    DockerService,
    _creation_lock_path,
    _load_or_create_session_state,
    _stop_owned_containers,
)
from pytest_databases.runtime import ResolvedRuntime, RuntimeType

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class FakeContainers:
    def __init__(self, listed: list[Any] | None = None) -> None:
        self.listed = listed or []
        self.list_calls: list[dict[str, Any]] = []
        self.run_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def list(self, **kwargs: Any) -> list[Any]:
        self.list_calls.append(kwargs)
        return self.listed

    def run(self, *args: Any, **kwargs: Any) -> object:
        self.run_calls.append((args, kwargs))
        return object()


class FakeClient:
    def __init__(self, containers: FakeContainers | None = None) -> None:
        self.containers = containers or FakeContainers()


class ConcurrentContainers(FakeContainers):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.maximum_active = 0
        self.guard = threading.Lock()

    def run(self, *args: Any, **kwargs: Any) -> object:
        with self.guard:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        time.sleep(0.03)
        with self.guard:
            self.active -= 1
        return super().run(*args, **kwargs)


def make_service(tmp_path: Path, *, owner_id: str = "a" * 32, client: FakeClient | None = None) -> ContainerService:
    return ContainerService(
        client=client or FakeClient(),  # type: ignore[arg-type]
        tmp_path=tmp_path,
        session=Mock(),
        owner_id=owner_id,
        runtime=ResolvedRuntime(RuntimeType.DOCKER, "unix:///docker.sock", "test"),
    )


def test_docker_service_is_a_compatibility_alias() -> None:
    assert DockerService is ContainerService
    assert PublicDockerService is PublicContainerService is ContainerService


def test_compatibility_fixtures_alias_new_fixture_names(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest


@pytest.fixture(scope="session")
def container_client():
    return object()


@pytest.fixture(scope="session")
def container_service():
    return object()


def test_aliases(container_client, docker_client, container_service, docker_service):
    assert docker_client is container_client
    assert docker_service is container_service
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_container_lookup_uses_exact_owner_and_service_labels(tmp_path: Path) -> None:
    container = object()
    containers = FakeContainers([container])
    service = make_service(tmp_path, client=FakeClient(containers))

    assert service._get_container("postgres") is container
    assert containers.list_calls == [
        {
            "filters": {
                "label": [
                    "pytest_databases=true",
                    f"pytest_databases.owner={'a' * 32}",
                    "pytest_databases.service=postgres",
                ]
            },
            "ignore_removed": True,
        }
    ]


def test_owner_names_make_same_logical_service_independent(tmp_path: Path) -> None:
    first = make_service(tmp_path, owner_id="a" * 32)
    second = make_service(tmp_path, owner_id="b" * 32)

    assert first.container_name("postgres") != second.container_name("postgres")
    assert first.container_name("postgres").endswith("aaaaaaaaaaaa")


def test_managed_run_injects_owner_labels_and_namespaced_name(tmp_path: Path) -> None:
    containers = FakeContainers()
    service = make_service(tmp_path, client=FakeClient(containers))

    service.run_container("busybox", "true", service_name="bootstrap", name="ignored")

    _, kwargs = containers.run_calls[0]
    assert kwargs["name"] == service.container_name("bootstrap")
    assert kwargs["labels"] == {
        "pytest_databases": "true",
        "pytest_databases.owner": "a" * 32,
        "pytest_databases.service": "bootstrap",
    }


def test_cleanup_filters_one_owner_and_leaves_other_sessions_unlisted() -> None:
    running = Mock(status="running")
    client = FakeClient(FakeContainers([running]))

    _stop_owned_containers(client, "session-a")  # type: ignore[arg-type]

    assert client.containers.list_calls[0]["filters"] == {"label": "pytest_databases.owner=session-a"}
    running.kill.assert_called_once_with()


def test_creation_lock_is_stable_per_runtime_and_user(tmp_path: Path) -> None:
    runtime = ResolvedRuntime(RuntimeType.PODMAN, "unix:///run/user/1000/podman/podman.sock", "test")

    assert _creation_lock_path(runtime, temp_directory=tmp_path, uid=1000) == _creation_lock_path(
        runtime, temp_directory=tmp_path, uid=1000
    )
    assert _creation_lock_path(runtime, temp_directory=tmp_path, uid=1000) != _creation_lock_path(
        runtime, temp_directory=tmp_path, uid=1001
    )


def test_creation_lock_serializes_different_services_on_one_daemon(tmp_path: Path) -> None:
    containers = ConcurrentContainers()
    runtime = ResolvedRuntime(RuntimeType.DOCKER, "unix:///issue-152-test.sock", "test")
    first = ContainerService(
        client=FakeClient(containers),  # type: ignore[arg-type]
        tmp_path=tmp_path,
        session=Mock(),
        owner_id="a" * 32,
        runtime=runtime,
    )
    second = ContainerService(
        client=FakeClient(containers),  # type: ignore[arg-type]
        tmp_path=tmp_path,
        session=Mock(),
        owner_id="b" * 32,
        runtime=runtime,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first.run_container, "busybox", service_name="postgres"),
            executor.submit(second.run_container, "busybox", service_name="mssql"),
        ]
        for future in futures:
            future.result()

    assert containers.maximum_active == 1


def test_session_state_is_shared_and_written_private(tmp_path: Path) -> None:
    calls = 0
    runtime = ResolvedRuntime(RuntimeType.PODMAN, "unix:///podman.sock", "test")

    def resolve(_choice: RuntimeType | str) -> ResolvedRuntime:
        nonlocal calls
        calls += 1
        return runtime

    first = _load_or_create_session_state(tmp_path, RuntimeType.AUTO, resolver=resolve)
    second = _load_or_create_session_state(tmp_path, RuntimeType.AUTO, resolver=resolve)

    assert first == second
    assert calls == 1
    assert stat.S_IMODE((tmp_path / "pytest-databases-session.json").stat().st_mode) == 0o600


def test_session_state_rejects_runtime_disagreement(tmp_path: Path) -> None:
    _load_or_create_session_state(
        tmp_path,
        RuntimeType.AUTO,
        resolver=lambda _: ResolvedRuntime(RuntimeType.DOCKER, "unix:///docker.sock", "test"),
    )

    def should_not_run(_choice: RuntimeType | str) -> ResolvedRuntime:
        raise AssertionError

    try:
        _load_or_create_session_state(tmp_path, RuntimeType.PODMAN, resolver=should_not_run)
    except RuntimeError as error:
        assert "already selected docker" in str(error)
    else:
        raise AssertionError
