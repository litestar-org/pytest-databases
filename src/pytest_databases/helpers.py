"""Helper utilities for hashing, pytest-xdist worker discovery, container output, and port probes."""

from __future__ import annotations

import hashlib
import os
import platform
import socket
import warnings
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

__all__ = (
    "exec_output_to_bytes",
    "get_cpu_architecture",
    "get_xdist_worker_count",
    "get_xdist_worker_id",
    "get_xdist_worker_num",
    "simple_string_hash",
    "tcp_port_open",
)


def exec_output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    """Normalize Docker ``exec_run`` output payloads into ``bytes``."""
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def simple_string_hash(string_to_hash: str) -> str:
    """Generate a deterministic 12-character SHA-256 hex digest prefix."""
    return hashlib.sha256(string_to_hash.encode("utf-8")).hexdigest()[:12]


def get_xdist_worker_id() -> str | None:
    """Return the active ``pytest-xdist`` worker identifier, if any."""
    return os.getenv("PYTEST_XDIST_WORKER")


def get_xdist_worker_num() -> int | None:
    """Return the numeric ``pytest-xdist`` worker index, or ``None`` on master."""
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return None
    return int(worker_id.replace("gw", ""))


def get_xdist_worker_count() -> int:
    """Return the configured ``pytest-xdist`` worker count."""
    return int(os.getenv("PYTEST_XDIST_WORKER_COUNT", "0"))


def get_cpu_architecture() -> Literal["x86_64", "arm", "unknown"]:
    """Detect whether the host CPU architecture is ``x86_64``, ``arm``, or ``unknown``."""
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine.startswith(("arm", "aarch")):
        return "arm"
    return "unknown"


def tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return whether a TCP connection to ``host:port`` can be opened from the test process.

    Readiness checks that run inside the container do not prove that the published host port is forwarded yet
    (rootless Podman, gvproxy, or Docker Desktop), so callers combine them with this probe.

    Args:
        host: Host name or IP address to connect to.
        port: TCP port to connect to.
        timeout: Connection timeout in seconds.

    Returns:
        True when the connection succeeds, otherwise False.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_legacy_platform(request: pytest.FixtureRequest, replacement: str | None, default: str | None) -> str | None:
    """Return a user override of the bare ``platform`` fixture, or ``default``.

    Up to v0.19.0 the MySQL, Dolt, and BigQuery services requested a fixture named ``platform``. The
    ``<backend>_platform`` fixtures replace it, and this function keeps a ``platform`` override defined
    outside ``pytest_databases`` (for example in a ``conftest.py``) working until v1.0.0. When such an
    override is visible from the requesting test, it emits one ``DeprecationWarning`` and returns the
    override's value.

    Args:
        request: The ``request`` of the fixture that used to depend on ``platform``.
        replacement: Fixture to override instead, or None when the image is multi-arch and needs no platform.
        default: Value to return when ``platform`` is not overridden.

    Returns:
        The overriding ``platform`` value, or ``default``.
    """
    fixturedefs = request._fixturemanager.getfixturedefs("platform", request._pyfuncitem)
    if not fixturedefs or fixturedefs[-1].func.__module__.startswith("pytest_databases."):
        return default
    guidance = (
        f"Override '{replacement}' instead."
        if replacement is not None
        else "The image is multi-arch, so remove the override; it is ignored from v1.0.0."
    )
    warnings.warn(
        f"Overriding the 'platform' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. {guidance}",
        DeprecationWarning,
        stacklevel=2,
    )
    return request.getfixturevalue("platform")
