"""Unit tests for container runtime resolution and discovery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from docker.errors import DockerException

from pytest_databases.helpers import exec_output_to_bytes, get_cpu_architecture, tcp_port_open
from pytest_databases.runtime import (
    ContainerRuntimeConfig,
    RuntimeCandidate,
    RuntimeResolutionError,
    RuntimeType,
    _default_probe,
    _podman_connection_uris,
    classify_runtime,
    default_host_from_base_url,
    discover_runtime_candidates,
    parse_runtime_type,
    resolve_container_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("auto", RuntimeType.AUTO),
        (" Docker ", RuntimeType.DOCKER),
        ("PODMAN", RuntimeType.PODMAN),
    ],
)
def test_parse_runtime_type(value: str, expected: RuntimeType) -> None:
    """Ensure runtime string is normalized to the corresponding enum value."""
    assert parse_runtime_type(value) is expected


def test_parse_runtime_type_rejects_unknown_value() -> None:
    """Ensure invalid runtime names raise ValueError."""
    with pytest.raises(ValueError, match="auto, docker, or podman"):
        parse_runtime_type("containerd")


@pytest.mark.parametrize(
    ("info", "version", "expected"),
    [
        pytest.param(
            {"Name": "fedora", "OperatingSystem": "fedora"},
            {
                "Components": [{"Name": "Podman Engine"}, {"Name": "Conmon"}],
                "Platform": {"Name": "linux/amd64/fedora-40"},
            },
            RuntimeType.PODMAN,
            id="podman-components",
        ),
        pytest.param(
            {"Name": "worker", "OperatingSystem": "Ubuntu 24.04"},
            {
                "Components": [{"Name": "Engine"}, {"Name": "containerd"}, {"Name": "runc"}],
                "Platform": {"Name": "Docker Engine - Community"},
            },
            RuntimeType.DOCKER,
            id="docker-components",
        ),
        pytest.param(
            {"Name": "podman-ci", "Labels": ["podman=true"], "RegistryConfig": {"Mirrors": ["https://libpod.example"]}},
            {"Components": [{"Name": "Engine"}], "Platform": {"Name": "Docker Engine - Community"}},
            RuntimeType.DOCKER,
            id="docker-host-named-podman",
        ),
        pytest.param(
            {"Name": "laptop", "OperatingSystem": "Docker Desktop"},
            {"Platform": {"Name": ""}},
            RuntimeType.DOCKER,
            id="docker-desktop-without-components",
        ),
        pytest.param(
            {"Name": "machine", "OperatingSystem": "podman-machine"},
            {},
            RuntimeType.PODMAN,
            id="podman-operating-system-without-components",
        ),
    ],
)
def test_classify_runtime(
    info: dict[str, object],
    version: dict[str, object],
    expected: RuntimeType,
) -> None:
    """Verify classification uses version components and ignores free-form host fields."""
    assert classify_runtime(info, version) is expected


def test_classify_runtime_rejects_unknown_compatibility_api() -> None:
    """Ensure unclassifiable server payloads raise RuntimeResolutionError."""
    with pytest.raises(RuntimeResolutionError, match="identify"):
        classify_runtime({"Name": "unknown"}, {"Platform": {"Name": "OCI Engine"}})


def test_environment_host_is_authoritative(tmp_path: Path) -> None:
    """Ensure explicit DOCKER_HOST environment variable takes precedence."""
    candidates = discover_runtime_candidates(
        environment={"DOCKER_HOST": "unix:///custom/podman.sock"},
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
    """Ensure candidate discovery deduplicates standard socket paths."""
    runtime_dir = tmp_path / "runtime"
    candidates = discover_runtime_candidates(
        environment={"XDG_RUNTIME_DIR": str(runtime_dir)},
        home=tmp_path,
        uid=1000,
        docker_context=None,
    )
    assert len({candidate.endpoint for candidate in candidates}) == len(candidates)
    assert candidates[0].expected_kind is RuntimeType.DOCKER
    assert any(candidate.expected_kind is RuntimeType.PODMAN for candidate in candidates)


def test_auto_prefers_reachable_docker_over_podman() -> None:
    """Ensure auto selection prioritizes Docker when both runtimes are reachable."""
    docker = RuntimeCandidate("unix:///docker.sock", "docker", RuntimeType.DOCKER)
    podman = RuntimeCandidate("unix:///podman.sock", "podman", RuntimeType.PODMAN)

    resolved = resolve_container_runtime(
        RuntimeType.AUTO,
        candidates=[podman, docker],
        probe=lambda candidate: candidate.expected_kind,
    )
    assert resolved == ContainerRuntimeConfig(RuntimeType.DOCKER, docker.endpoint, docker.source)


def test_explicit_runtime_never_falls_back_to_other_engine() -> None:
    """Ensure requested Podman runtime does not fall back to an active Docker endpoint."""
    candidate = RuntimeCandidate("unix:///docker.sock", "DOCKER_HOST", None)

    with pytest.raises(RuntimeResolutionError, match=r"requested podman.*reported docker"):
        resolve_container_runtime(
            RuntimeType.PODMAN,
            candidates=[candidate],
            probe=lambda _: RuntimeType.DOCKER,
        )


def test_resolution_sanitizes_endpoint_credentials() -> None:
    """Ensure credentials embedded in URLs are sanitized in error diagnostics."""
    candidate = RuntimeCandidate("tcp://user:secret@example.test:2376", "CONTAINER_HOST", None)

    with pytest.raises(RuntimeResolutionError) as exc_info:
        resolve_container_runtime(RuntimeType.DOCKER, candidates=[candidate], probe=lambda _: None)

    assert "secret" not in str(exc_info.value)
    assert "***@example.test" in str(exc_info.value)


@pytest.mark.parametrize(
    ("base_url", "expected_host"),
    [
        ("", "127.0.0.1"),
        ("unix:///var/run/docker.sock", "127.0.0.1"),
        ("unix:///run/user/1000/podman/podman.sock", "127.0.0.1"),
        ("npipe:////./pipe/docker_engine", "127.0.0.1"),
        ("tcp://192.168.1.150:2375", "192.168.1.150"),
        ("http://remote.local:2375", "remote.local"),
        ("https://remote.internal:2376", "remote.internal"),
        ("ssh://user@jump.internal:22", "jump.internal"),
    ],
)
def test_default_host_from_base_url(base_url: str, expected_host: str) -> None:
    """Verify host extraction across local and remote endpoint transports."""
    assert default_host_from_base_url(base_url) == expected_host


def test_container_host_environment_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CONTAINER_HOST populates DOCKER_HOST in client environment."""
    candidates = discover_runtime_candidates(environment={"CONTAINER_HOST": "unix:///run/podman.sock"})
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.expected_kind is RuntimeType.PODMAN
    env_dict = dict(candidate.environment or ())
    assert env_dict.get("DOCKER_HOST") == "unix:///run/podman.sock"

    mock_client = MagicMock()
    mock_from_env = MagicMock(return_value=mock_client)
    monkeypatch.setattr("pytest_databases.runtime.DockerClient.from_env", mock_from_env)

    config = ContainerRuntimeConfig(
        kind=RuntimeType.PODMAN,
        endpoint="unix:///run/podman.sock",
        source="CONTAINER_HOST",
        environment=candidate.environment,
    )
    client = config.create_client()
    assert client is mock_client
    call_env = mock_from_env.call_args[1]["environment"]
    assert call_env.get("DOCKER_HOST") == "unix:///run/podman.sock"


def test_resolve_from_env_var() -> None:
    """Verify runtime preference is read from PYTEST_DATABASES_CONTAINER_RUNTIME."""
    podman = RuntimeCandidate("unix:///podman.sock", "podman", RuntimeType.PODMAN)
    resolved = resolve_container_runtime(
        None,
        candidates=[podman],
        probe=lambda candidate: candidate.expected_kind,
        environment={"PYTEST_DATABASES_CONTAINER_RUNTIME": "podman"},
    )
    assert resolved.kind is RuntimeType.PODMAN


def test_container_runtime_config_create_client_with_context() -> None:
    """Verify client construction with Docker context."""
    config = ContainerRuntimeConfig(
        kind=RuntimeType.DOCKER,
        endpoint="unix:///custom.sock",
        source="test",
        context_name="invalid-context-name",
    )
    with pytest.raises(RuntimeResolutionError, match="unavailable"):
        config.create_client()


def test_container_runtime_config_create_client_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify client construction directly from base_url."""
    mock_client = MagicMock()
    mock_docker_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr("pytest_databases.runtime.DockerClient", mock_docker_cls)

    config = ContainerRuntimeConfig(
        kind=RuntimeType.DOCKER,
        endpoint="unix:///run/docker.sock",
        source="default Docker socket",
    )
    client = config.create_client()
    assert client is mock_client
    mock_docker_cls.assert_called_once_with(base_url="unix:///run/docker.sock", timeout=60)


def test_runtime_context_and_podman_connections_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify Docker context branches, podman connection JSON parsing, and _default_probe success."""
    mock_context = MagicMock(Host="tcp://10.0.0.5:2376", TLSConfig=None, Name="remote")
    monkeypatch.setattr("pytest_databases.runtime.ContextAPI.get_context", lambda _name: mock_context)
    mock_client = MagicMock()
    mock_client.info.return_value = {"OperatingSystem": "Docker Desktop"}
    mock_client.version.return_value = {"Components": [{"Name": "Engine"}]}
    monkeypatch.setattr("pytest_databases.runtime.DockerClient", MagicMock(return_value=mock_client))

    ctx_config = ContainerRuntimeConfig(
        kind=RuntimeType.DOCKER,
        endpoint="tcp://10.0.0.5:2376",
        source="ctx",
        context_name="remote",
    )
    assert ctx_config.create_client() is mock_client

    env_config = ContainerRuntimeConfig(
        kind=RuntimeType.DOCKER,
        endpoint="tcp://10.0.0.6:2375",
        source="env",
        environment=(("DOCKER_TLS_VERIFY", "0"),),
    )
    mock_from_env = MagicMock(return_value=mock_client)
    monkeypatch.setattr("pytest_databases.runtime.DockerClient.from_env", mock_from_env)
    assert env_config.create_client() is mock_client
    assert mock_from_env.call_args.kwargs["environment"]["DOCKER_HOST"] == "tcp://10.0.0.6:2375"

    def _raise_docker_exc() -> None:
        msg = "no context"
        raise DockerException(msg)

    monkeypatch.setattr("pytest_databases.runtime.ContextAPI.get_current_context", _raise_docker_exc)
    conn_dir = tmp_path / ".config" / "containers"
    conn_dir.mkdir(parents=True)
    conn_file = conn_dir / "podman-connections.json"
    conn_file.write_text(
        json.dumps({
            "connections": [
                {"uri": "ssh://root@localhost/run/podman/podman.sock"},
                {"nested": {"URI": "unix:///tmp/podman2.sock"}},
            ]
        })
    )
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not-json")
    assert _podman_connection_uris(bad_file) == []
    assert _podman_connection_uris(tmp_path / "missing.json") == []

    candidates = discover_runtime_candidates(environment={}, home=tmp_path, uid=1000)
    endpoints = [c.endpoint for c in candidates]
    assert "ssh://root@localhost/run/podman/podman.sock" in endpoints
    assert "unix:///tmp/podman2.sock" in endpoints

    empty_ctx = MagicMock(Host=None, Name="empty")
    candidates_empty_ctx = discover_runtime_candidates(
        environment={},
        docker_context=empty_ctx,
        home=tmp_path,
        uid=1000,
    )
    assert any(c.source == "default Docker socket" for c in candidates_empty_ctx)

    docker_cand = RuntimeCandidate("unix:///var/run/docker.sock", "docker", RuntimeType.DOCKER)
    podman_cand = RuntimeCandidate("unix:///run/podman.sock", "podman", RuntimeType.PODMAN)
    resolved = resolve_container_runtime(
        RuntimeType.PODMAN,
        candidates=[docker_cand, podman_cand],
        probe=lambda c: c.expected_kind,
    )
    assert resolved.kind is RuntimeType.PODMAN

    assert _default_probe(docker_cand) is RuntimeType.DOCKER
    mock_client.close.assert_called()


@pytest.mark.parametrize(
    ("machine", "expected_arch"),
    [
        ("x86_64", "x86_64"),
        ("AMD64", "x86_64"),
        ("aarch64", "arm"),
        ("arm64", "arm"),
        ("riscv64", "unknown"),
    ],
)
def test_helpers_cpu_arch_and_exec_output_and_tcp_probe(
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
    expected_arch: str,
) -> None:
    """Verify get_cpu_architecture, exec_output_to_bytes, and tcp_port_open helper branches."""
    monkeypatch.setattr("pytest_databases.helpers.platform.machine", lambda: machine)
    assert get_cpu_architecture() == expected_arch
    assert exec_output_to_bytes("hello") == b"hello"
    assert exec_output_to_bytes(iter([b"hel", b"lo"])) == b"hello"

    monkeypatch.setattr("pytest_databases.helpers.socket.create_connection", lambda *_a, **_kw: MagicMock())
    assert tcp_port_open("127.0.0.1", 5432) is True

    def _fail_conn(*_a: object, **_kw: object) -> None:
        msg = "refused"
        raise OSError(msg)

    monkeypatch.setattr("pytest_databases.helpers.socket.create_connection", _fail_conn)
    assert tcp_port_open("127.0.0.1", 5432) is False
