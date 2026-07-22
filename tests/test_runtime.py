from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.runtime import (
    ResolvedRuntime,
    RuntimeCandidate,
    RuntimeResolutionError,
    RuntimeType,
    classify_runtime,
    discover_runtime_candidates,
    parse_runtime_type,
    resolve_container_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("value", "expected"),
    [("auto", RuntimeType.AUTO), (" Docker ", RuntimeType.DOCKER), ("PODMAN", RuntimeType.PODMAN)],
)
def test_parse_runtime_type(value: str, expected: RuntimeType) -> None:
    assert parse_runtime_type(value) is expected


def test_parse_runtime_type_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="auto, docker, or podman"):
        parse_runtime_type("containerd")


@pytest.mark.parametrize(
    ("info", "version", "expected"),
    [
        ({"Components": [{"Name": "Podman Engine"}]}, {"Platform": {"Name": "Podman Engine"}}, RuntimeType.PODMAN),
        ({"Name": "worker"}, {"Platform": {"Name": "Docker Engine - Community"}}, RuntimeType.DOCKER),
    ],
)
def test_classify_runtime(info: dict[str, object], version: dict[str, object], expected: RuntimeType) -> None:
    assert classify_runtime(info, version) is expected


def test_classify_runtime_rejects_unknown_compatibility_api() -> None:
    with pytest.raises(RuntimeResolutionError, match="identify"):
        classify_runtime({"Name": "unknown"}, {"Platform": {"Name": "OCI Engine"}})


def test_environment_host_is_authoritative(tmp_path: Path) -> None:
    candidates = discover_runtime_candidates(
        environ={"DOCKER_HOST": "unix:///custom/podman.sock"},
        home=tmp_path,
        uid=1000,
    )

    assert candidates == [
        RuntimeCandidate(
            endpoint="unix:///custom/podman.sock",
            source="DOCKER_HOST",
            expected_kind=None,
            environment=(("DOCKER_HOST", "unix:///custom/podman.sock"),),
        )
    ]


def test_discovery_deduplicates_standard_sockets(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    candidates = discover_runtime_candidates(
        environ={"XDG_RUNTIME_DIR": str(runtime_dir)},
        home=tmp_path,
        uid=1000,
        docker_context=None,
    )

    assert len({candidate.endpoint for candidate in candidates}) == len(candidates)
    assert candidates[0].expected_kind is RuntimeType.DOCKER
    assert any(candidate.expected_kind is RuntimeType.PODMAN for candidate in candidates)


def test_auto_prefers_reachable_docker_over_podman() -> None:
    docker = RuntimeCandidate("unix:///docker.sock", "docker", RuntimeType.DOCKER)
    podman = RuntimeCandidate("unix:///podman.sock", "podman", RuntimeType.PODMAN)

    resolved = resolve_container_runtime(
        RuntimeType.AUTO,
        candidates=[podman, docker],
        probe=lambda candidate: candidate.expected_kind,
    )

    assert resolved == ResolvedRuntime(RuntimeType.DOCKER, docker.endpoint, docker.source)


def test_explicit_runtime_never_falls_back_to_other_engine() -> None:
    candidate = RuntimeCandidate("unix:///docker.sock", "DOCKER_HOST", None)

    with pytest.raises(RuntimeResolutionError, match=r"requested podman.*reported docker"):
        resolve_container_runtime(
            RuntimeType.PODMAN,
            candidates=[candidate],
            probe=lambda _: RuntimeType.DOCKER,
        )


def test_resolution_sanitizes_endpoint_credentials() -> None:
    candidate = RuntimeCandidate("tcp://user:secret@example.test:2376", "CONTAINER_HOST", None)

    with pytest.raises(RuntimeResolutionError) as exc_info:
        resolve_container_runtime(RuntimeType.DOCKER, candidates=[candidate], probe=lambda _: None)

    assert "secret" not in str(exc_info.value)
    assert "***@example.test" in str(exc_info.value)
