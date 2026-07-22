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
    identity = json.dumps({"info": info, "version": version}, sort_keys=True, default=str).lower()
    if "podman" in identity or "libpod" in identity:
        return RuntimeType.PODMAN
    if "docker" in identity or "moby" in identity:
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
    for variable in ("CONTAINER_HOST", "DOCKER_HOST"):
        if endpoint := environment.get(variable, "").strip():
            transport_environment = tuple(
                sorted(
                    (key, value)
                    for key, value in environment.items()
                    if key in {"DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}
                )
            )
            return [RuntimeCandidate(endpoint, variable, None, environment=transport_environment)]

    candidates: list[RuntimeCandidate] = []
    if docker_context is _DEFAULT_CONTEXT:
        try:
            docker_context = ContextAPI.get_current_context()
        except (DockerException, KeyError, OSError, ValueError):
            docker_context = None
    if docker_context is not None:
        context_endpoint = getattr(docker_context, "Host", None)
        name = getattr(docker_context, "Name", None)
        if context_endpoint:
            candidates.append(
                RuntimeCandidate(str(context_endpoint), f"Docker context {name}", RuntimeType.DOCKER, str(name))
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


def _default_probe(candidate: RuntimeCandidate) -> RuntimeType | None:
    descriptor = ResolvedRuntime(
        kind=candidate.expected_kind or RuntimeType.DOCKER,
        endpoint=candidate.endpoint,
        source=candidate.source,
        context_name=candidate.context_name,
        environment=candidate.environment,
    )
    client: DockerClient | None = None
    try:
        client = descriptor.create_client()
        return classify_runtime(client.info(), client.version())
    except (DockerException, ImportError, OSError, RuntimeResolutionError):
        return None
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
    if runtime_type is RuntimeType.AUTO:
        available.sort(
            key=lambda candidate: (
                0
                if candidate.expected_kind is RuntimeType.DOCKER
                else 2
                if candidate.expected_kind is RuntimeType.PODMAN
                else 1
            )
        )
    attempted: list[str] = []
    for candidate in available:
        if runtime_type is not RuntimeType.AUTO and candidate.expected_kind not in {None, runtime_type}:
            continue
        actual_kind = probe(candidate)
        attempted.append(f"{candidate.source} ({_sanitize_endpoint(candidate.endpoint)})")
        if actual_kind is None:
            continue
        if runtime_type is not RuntimeType.AUTO and actual_kind is not runtime_type:
            message = (
                f"requested {runtime_type.value} from {candidate.source}, but endpoint "
                f"{_sanitize_endpoint(candidate.endpoint)} reported {actual_kind.value}"
            )
            raise RuntimeResolutionError(message)
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
