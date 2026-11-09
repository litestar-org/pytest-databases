"""Unit tests for deterministic session ownership and scoped cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from pytest_databases import (
    MANAGED_LABEL,
    OWNER_LABEL,
    SERVICE_LABEL,
    ContainerService,
    DockerService,
    derive_session_owner_id,
    stop_owned_containers,
)
from pytest_databases._service import _RUNTIME_STASH_KEY, _cleanup_session_containers
from pytest_databases.runtime import ContainerRuntimeConfig, RuntimeResolutionError, RuntimeType

if TYPE_CHECKING:
    from pathlib import Path


class FakeContainers:
    """Mock container collection for testing ownership filtering."""

    def __init__(self, listed: list[Any] | None = None) -> None:
        self.listed = listed or []
        self.list_calls: list[dict[str, Any]] = []
        self.run_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def list(self, **kwargs: Any) -> list[Any]:
        """Record list invocation and return canned container list."""
        self.list_calls.append(kwargs)
        return self.listed

    def run(self, *args: Any, **kwargs: Any) -> object:
        """Record run invocation and return a stub container object."""
        self.run_calls.append((args, kwargs))
        return MagicMock()


class FakeClient:
    """Mock DockerClient with controlled container collections."""

    def __init__(self, containers: FakeContainers | None = None) -> None:
        self.containers = containers or FakeContainers()
        self.close_calls = 0

    def close(self) -> None:
        """Record client close."""
        self.close_calls += 1


def make_service(
    tmp_path: Path,
    *,
    owner_id: str = "a" * 12,
    client: FakeClient | None = None,
) -> ContainerService:
    """Helper to construct a ContainerService with fake dependencies."""
    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    runtime_config = ContainerRuntimeConfig(RuntimeType.DOCKER, "unix:///docker.sock", "test")
    return ContainerService(
        client=cast("Any", client or FakeClient()),
        tmp_path=tmp_path,
        session=mock_session,
        runtime_config=runtime_config,
        owner_id=owner_id,
    )


def test_docker_service_is_a_compatibility_alias() -> None:
    """Ensure DockerService is an alias for ContainerService."""
    assert DockerService is ContainerService


def test_derive_session_owner_id_is_deterministic(tmp_path: Path) -> None:
    """Ensure identical paths produce identical 12-char hex digests."""
    first = derive_session_owner_id(tmp_path)
    second = derive_session_owner_id(tmp_path)
    assert first == second
    assert len(first) == 12
    assert all(c in "0123456789abcdef" for c in first)


def test_derive_session_owner_id_distinguishes_different_paths(tmp_path: Path) -> None:
    """Ensure distinct paths produce distinct owner digests."""
    dir_a = tmp_path / "worktree_a"
    dir_b = tmp_path / "worktree_b"
    dir_a.mkdir()
    dir_b.mkdir()
    assert derive_session_owner_id(dir_a) != derive_session_owner_id(dir_b)


def test_derive_session_owner_id_with_namespace(tmp_path: Path) -> None:
    """Ensure namespace suffix is sanitized and appended."""
    owner = derive_session_owner_id(tmp_path, namespace="CI-Job-123!")
    assert owner.endswith("_ci_job_123")


def test_derive_session_owner_id_with_env_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure PYTEST_DATABASES_NAMESPACE environment variable is honored."""
    monkeypatch.setenv("PYTEST_DATABASES_NAMESPACE", "env_worker_42")
    owner = derive_session_owner_id(tmp_path)
    assert owner.endswith("_env_worker_42")


def test_container_lookup_uses_exact_owner_and_service_labels(tmp_path: Path) -> None:
    """Ensure _get_container filters specifically by managed, owner, and service labels."""
    container = MagicMock()
    containers = FakeContainers([container])
    service = make_service(tmp_path, client=FakeClient(containers), owner_id="1234567890ab")

    assert service._get_container("postgres") is container
    assert containers.list_calls == [
        {
            "filters": {
                "label": [
                    f"{MANAGED_LABEL}=true",
                    f"{OWNER_LABEL}=1234567890ab",
                    f"{SERVICE_LABEL}=postgres",
                ]
            },
            "ignore_removed": True,
        }
    ]


def test_owner_names_make_same_logical_service_independent(tmp_path: Path) -> None:
    """Ensure separate owner IDs generate distinct container names."""
    first = make_service(tmp_path, owner_id="111111111111")
    second = make_service(tmp_path, owner_id="222222222222")

    assert first.container_name("postgres") != second.container_name("postgres")
    assert first.container_name("postgres").endswith("111111111111")
    assert second.container_name("postgres").endswith("222222222222")


def test_managed_run_container_injects_owner_labels_and_namespaced_name(
    tmp_path: Path,
) -> None:
    """Ensure run_container helper attaches ownership metadata."""
    containers = FakeContainers()
    service = make_service(tmp_path, client=FakeClient(containers), owner_id="abcdef123456")

    service.run_container("busybox:latest", "true", service_name="bootstrap")

    assert len(containers.run_calls) == 1
    _, kwargs = containers.run_calls[0]
    assert kwargs["name"] == service.container_name("bootstrap")
    assert kwargs["labels"] == {
        MANAGED_LABEL: "true",
        OWNER_LABEL: "abcdef123456",
        SERVICE_LABEL: "bootstrap",
    }


def test_cleanup_filters_one_owner_and_leaves_other_sessions_unlisted() -> None:
    """Ensure stop_owned_containers filters strictly by the target owner ID."""
    running = MagicMock(status="running")
    client = FakeClient(FakeContainers([running]))

    stop_owned_containers(cast("Any", client), "target-owner-id")

    assert client.containers.list_calls[0]["filters"] == {"label": f"{OWNER_LABEL}=target-owner-id"}
    running.kill.assert_called_once_with()


def test_container_service_lifecycle_cleans_owned_containers(tmp_path: Path) -> None:
    """Ensure __enter__ and __exit__ trigger scoped cleanup of owned containers."""
    stray_container = MagicMock(status="running")
    containers = FakeContainers([stray_container])
    client = FakeClient(containers)
    service = make_service(tmp_path, client=client, owner_id="session123456")

    with service:
        stray_container.kill.assert_called_once_with()
        stray_container.kill.reset_mock()

    stray_container.kill.assert_called_once_with()


def test_container_service_records_owner_in_control_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure entering the service writes its owner to the session control file."""
    ctrl_file = tmp_path / "ctrl"
    monkeypatch.setattr("pytest_databases._service._get_ctrl_file", lambda _session: ctrl_file)
    service = make_service(tmp_path, owner_id="custom-owner")

    with service:
        assert ctrl_file.read_text(encoding="utf-8") == "custom-owner"


def make_finishing_session(tmp_path: Path, runtime: ContainerRuntimeConfig | None) -> MagicMock:
    """Build a session whose config carries a real stash and rootpath."""
    session = MagicMock()
    session.config.rootpath = tmp_path
    session.config.stash = pytest.Stash()
    session.config.getoption.return_value = None
    session.config.getini.return_value = ""
    if runtime is not None:
        session.config.stash[_RUNTIME_STASH_KEY] = runtime
    return session


def test_session_cleanup_reuses_stashed_runtime_and_recorded_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure controller cleanup uses the resolved runtime and the owner written to the control file."""
    ctrl_file = tmp_path / "ctrl"
    ctrl_file.write_text("recorded-owner", encoding="utf-8")
    client = FakeClient()
    runtime = MagicMock(spec=ContainerRuntimeConfig)
    runtime.create_client.return_value = client

    def fail_resolution(*_args: object, **_kwargs: object) -> ContainerRuntimeConfig:
        msg = "should not resolve again"
        raise AssertionError(msg)

    monkeypatch.setattr("pytest_databases._service.resolve_container_runtime", fail_resolution)
    _cleanup_session_containers(make_finishing_session(tmp_path, runtime), ctrl_file)

    assert client.containers.list_calls[0]["filters"] == {"label": f"{OWNER_LABEL}=recorded-owner"}
    assert client.close_calls == 1


def test_session_cleanup_warns_instead_of_raising_on_resolution_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure a runtime resolution failure at session end becomes a warning."""
    ctrl_file = tmp_path / "ctrl"
    ctrl_file.write_text("recorded-owner", encoding="utf-8")

    def unavailable(*_args: object, **_kwargs: object) -> ContainerRuntimeConfig:
        msg = "no runtime reachable"
        raise RuntimeResolutionError(msg)

    monkeypatch.setattr("pytest_databases._service.resolve_container_runtime", unavailable)

    with pytest.warns(RuntimeWarning, match="no runtime reachable"):
        _cleanup_session_containers(make_finishing_session(tmp_path, None), ctrl_file)
