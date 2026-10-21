"""Unit tests for deterministic session ownership and scoped cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from pytest_databases import (
    MANAGED_LABEL,
    OWNER_LABEL,
    SERVICE_LABEL,
    ContainerService,
    DockerService,
    derive_session_owner_id,
    stop_owned_containers,
)
from pytest_databases.runtime import ContainerRuntimeConfig, RuntimeType

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
        client=client or FakeClient(),  # type: ignore[arg-type]
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

    stop_owned_containers(client, "target-owner-id")  # type: ignore[arg-type]

    assert client.containers.list_calls[0]["filters"] == {
        "label": f"{OWNER_LABEL}=target-owner-id"
    }
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
