"""Helper utilities for hashing, pytest-xdist worker discovery, and container output."""

from __future__ import annotations

import hashlib
import os
import platform
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = (
    "exec_output_to_bytes",
    "get_cpu_architecture",
    "get_xdist_worker_count",
    "get_xdist_worker_id",
    "get_xdist_worker_num",
    "simple_string_hash",
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
