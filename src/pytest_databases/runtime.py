"""Container runtime discovery over the Docker-compatible HTTP API."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from docker.context import ContextAPI
from docker.errors import DockerException

from docker import DockerClient

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_DEFAULT_CONTEXT = object()
_CREDENTIAL_PATTERN = re.compile(r"(?<=://)[^/@]+@")


class RuntimeType(str, Enum):
    """Supported container runtime choices."""

    AUTO = "auto"
    DOCKER = "docker"
    PODMAN = "podman"


class RuntimeResolutionError(RuntimeError):
    """Raised when no compatible container API endpoint can be resolved."""


@dataclass(frozen=True)
class RuntimeCandidate:
    """A Docker-compatible API endpoint that can be probed."""

    endpoint: str
    source: str
    expected_kind: RuntimeType | None
    context_name: str | None = None
    environment: tuple[tuple[str, str], ...] = ()
    authoritative: bool = False


@dataclass(frozen=True)
class ResolvedRuntime:
    """Serializable transport descriptor for one verified runtime."""

    kind: RuntimeType
    endpoint: str
    source: str
    context_name: str | None = None
    environment: tuple[tuple[str, str], ...] = ()
    timeout: int = 60

    def create_client(self) -> DockerClient:
        """Construct a client for the exact transport that was resolved."""
        if self.context_name is not None:
            context = ContextAPI.get_context(self.context_name)
            if context is None or context.Host is None:
                message = f"Docker context {self.context_name!r} is unavailable"
                raise RuntimeResolutionError(message)
            if str(context.Host) != self.endpoint:
                message = (
                    f"Docker context {self.context_name!r} changed from {self.endpoint!r} "
                    f"to {str(context.Host)!r} after runtime selection"
                )
                raise RuntimeResolutionError(message)
            return DockerClient(base_url=context.Host, tls=context.TLSConfig, timeout=self.timeout)
        if self.environment:
            return DockerClient.from_env(environment=dict(self.environment), timeout=self.timeout)
        return DockerClient(base_url=self.endpoint, timeout=self.timeout)

    def to_dict(self) -> dict[str, object]:
        """Serialize the transport without credentials from diagnostic strings."""
        return {
            "kind": self.kind.value,
            "endpoint": self.endpoint,
            "source": self.source,
            "context_name": self.context_name,
            "environment": dict(self.environment),
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ResolvedRuntime:
        """Restore a transport descriptor written by another xdist process."""
        environment = value.get("environment", {})
        if not isinstance(environment, Mapping):
            message = "runtime environment descriptor must be a mapping"
            raise RuntimeResolutionError(message)
        timeout = value.get("timeout", 60)
        if not isinstance(timeout, (int, str)):
            message = "runtime timeout descriptor must be an integer"
            raise RuntimeResolutionError(message)
        return cls(
            kind=RuntimeType(str(value["kind"])),
            endpoint=str(value["endpoint"]),
            source=str(value["source"]),
            context_name=str(value["context_name"]) if value.get("context_name") is not None else None,
            environment=tuple(sorted((str(key), str(item)) for key, item in environment.items())),
            timeout=int(timeout),
        )


def parse_runtime_type(value: RuntimeType | str) -> RuntimeType:
    """Normalize a fixture or environment runtime choice."""
    if isinstance(value, RuntimeType):
        return value
    try:
        return RuntimeType(value.strip().lower())
    except ValueError as error:
        message = "container runtime must be auto, docker, or podman"
        raise ValueError(message) from error


def classify_runtime(info: Mapping[str, object], version: Mapping[str, object]) -> RuntimeType:
    """Classify a reachable compatibility API from its server payloads."""
    del info
    markers: list[str] = []
    platform = version.get("Platform")
    if isinstance(platform, Mapping) and isinstance(platform.get("Name"), str):
        markers.append(platform["Name"])
    components = version.get("Components")
    if isinstance(components, list):
        markers.extend(
            component["Name"]
            for component in components
            if isinstance(component, Mapping) and isinstance(component.get("Name"), str)
        )
    identity = " ".join(markers).lower()
    is_podman = "podman" in identity or "libpod" in identity
    is_docker = "docker" in identity or "moby" in identity
    if is_podman and is_docker:
        message = "container API returned conflicting Docker and Podman identity fields"
        raise RuntimeResolutionError(message)
    if is_podman:
        return RuntimeType.PODMAN
    if is_docker:
        return RuntimeType.DOCKER
    message = "reachable container API could not identify itself as Docker or Podman"
    raise RuntimeResolutionError(message)


def _podman_connection_uris(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    uris: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() == "uri" and isinstance(item, str):
                    uris.append(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return uris


def discover_runtime_candidates(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    uid: int | None = None,
    docker_context: object = _DEFAULT_CONTEXT,
) -> list[RuntimeCandidate]:
    """Discover endpoints without invoking Docker, systemctl, sudo, or machine startup."""
    environment = dict(os.environ if environ is None else environ)
    selected_variable = next(
        (variable for variable in ("CONTAINER_HOST", "DOCKER_HOST") if environment.get(variable, "").strip()),
        None,
    )
    if selected_variable is not None:
        endpoint = environment[selected_variable].strip()
        transport_environment = {"DOCKER_HOST": endpoint}
        transport_environment.update(
            (key, environment[key]) for key in ("DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH") if key in environment
        )
        return [
            RuntimeCandidate(
                endpoint,
                selected_variable,
                None,
                environment=tuple(sorted(transport_environment.items())),
                authoritative=True,
            )
        ]

    candidates: list[RuntimeCandidate] = []
    if docker_context is _DEFAULT_CONTEXT:
        try:
            context_name = environment.get("DOCKER_CONTEXT", "").strip()
            docker_context = ContextAPI.get_context(context_name) if context_name else ContextAPI.get_current_context()
        except (DockerException, KeyError, OSError, ValueError):
            docker_context = None
    if docker_context is not None:
        context_endpoint = getattr(docker_context, "Host", None)
        name = getattr(docker_context, "Name", None)
        if context_endpoint:
            candidates.append(
                RuntimeCandidate(
                    str(context_endpoint),
                    f"Docker context {name}",
                    None,
                    str(name) if name is not None else None,
                    authoritative=bool(environment.get("DOCKER_CONTEXT", "").strip()),
                )
            )

    candidates.append(RuntimeCandidate("unix:///var/run/docker.sock", "default Docker socket", RuntimeType.DOCKER))
    resolved_home = Path.home() if home is None else home
    connection_files = [
        resolved_home / ".config" / "containers" / "podman-connections.json",
        resolved_home / ".local" / "share" / "containers" / "podman" / "connections.json",
    ]
    for connection_file in connection_files:
        candidates.extend(
            RuntimeCandidate(uri, f"Podman connection {connection_file}", RuntimeType.PODMAN)
            for uri in _podman_connection_uris(connection_file)
        )
    resolved_uid = os.getuid() if uid is None and hasattr(os, "getuid") else (uid or 0)
    runtime_dir = Path(environment.get("XDG_RUNTIME_DIR", f"/run/user/{resolved_uid}"))
    candidates.extend([
        RuntimeCandidate(
            f"unix://{runtime_dir / 'podman' / 'podman.sock'}", "rootless Podman socket", RuntimeType.PODMAN
        ),
        RuntimeCandidate("unix:///run/podman/podman.sock", "rootful Podman socket", RuntimeType.PODMAN),
    ])
    deduplicated: dict[str, RuntimeCandidate] = {}
    for candidate in candidates:
        deduplicated.setdefault(candidate.endpoint, candidate)
    return list(deduplicated.values())


def _sanitize_endpoint(endpoint: str) -> str:
    return _CREDENTIAL_PATTERN.sub("***@", endpoint)


def _default_probe(candidate: RuntimeCandidate) -> RuntimeType:
    descriptor = ResolvedRuntime(
        kind=candidate.expected_kind or RuntimeType.DOCKER,
        endpoint=candidate.endpoint,
        source=candidate.source,
        context_name=candidate.context_name,
        environment=candidate.environment,
        timeout=5,
    )
    client: DockerClient | None = None
    try:
        client = descriptor.create_client()
        return classify_runtime(client.info(), client.version())
    except (DockerException, ImportError, OSError, RuntimeResolutionError) as error:
        message = f"{type(error).__name__} while probing endpoint"
        raise RuntimeResolutionError(message) from error
    finally:
        if client is not None:
            client.close()


def resolve_container_runtime(
    requested: RuntimeType | str = RuntimeType.AUTO,
    *,
    candidates: Sequence[RuntimeCandidate] | None = None,
    probe: Callable[[RuntimeCandidate], RuntimeType | None] = _default_probe,
) -> ResolvedRuntime:
    """Resolve a reachable runtime with Docker-first auto semantics."""
    runtime_type = parse_runtime_type(requested)
    available = list(discover_runtime_candidates() if candidates is None else candidates)
    attempted: list[str] = []
    podman_fallback: tuple[RuntimeCandidate, RuntimeType] | None = None
    for candidate in available:
        if runtime_type is not RuntimeType.AUTO and candidate.expected_kind not in {None, runtime_type}:
            continue
        if runtime_type is RuntimeType.AUTO and podman_fallback is not None and candidate.expected_kind is RuntimeType.PODMAN:
            continue
        attempted_endpoint = f"{candidate.source} ({_sanitize_endpoint(candidate.endpoint)})"
        try:
            actual_kind = probe(candidate)
        except RuntimeResolutionError as error:
            attempted.append(f"{attempted_endpoint}: {error}")
            continue
        if actual_kind is None:
            attempted.append(f"{attempted_endpoint}: unavailable")
            continue
        attempted.append(f"{attempted_endpoint}: reported {actual_kind.value}")
        if runtime_type is RuntimeType.AUTO and actual_kind is RuntimeType.PODMAN:
            if podman_fallback is None:
                podman_fallback = (candidate, actual_kind)
            continue
        if runtime_type is not RuntimeType.AUTO and actual_kind is not runtime_type:
            if candidate.authoritative:
                message = (
                    f"requested {runtime_type.value} from {candidate.source}, but endpoint "
                    f"{_sanitize_endpoint(candidate.endpoint)} reported {actual_kind.value}"
                )
                raise RuntimeResolutionError(message)
            continue
        return ResolvedRuntime(
            actual_kind,
            candidate.endpoint,
            candidate.source,
            candidate.context_name,
            candidate.environment,
        )
    if podman_fallback is not None:
        candidate, actual_kind = podman_fallback
        return ResolvedRuntime(
            actual_kind,
            candidate.endpoint,
            candidate.source,
            candidate.context_name,
            candidate.environment,
        )
    attempted_text = ", ".join(attempted) or "no candidates"
    message = (
        f"could not connect to requested {runtime_type.value} runtime; attempted {attempted_text}. "
        "Start Docker, enable `systemctl --user enable --now podman.socket` on Linux, or set DOCKER_HOST/CONTAINER_HOST."
    )
    raise RuntimeResolutionError(message)
