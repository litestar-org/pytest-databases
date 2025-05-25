from __future__ import annotations

import hashlib
import os
import platform
from typing import Literal


def simple_string_hash(string_to_hash: str) -> str:
    """Generates a short hash based on a string.

    Args:
      string_to_hash: The string to hash.

    Returns:
      A short hash string.
    """

    string_bytes = string_to_hash.encode("utf-8")
    hasher = hashlib.sha256()
    hasher.update(string_bytes)
    digest = hasher.digest()
    hex_string = digest.hex()
    return hex_string[:12]


def get_xdist_worker_id() -> str | None:
    return os.getenv("PYTEST_XDIST_WORKER")


def get_xdist_worker_num() -> int | None:
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return None
    return int(worker_id.replace("gw", ""))


def get_xdist_worker_count() -> int:
    return int(os.getenv("PYTEST_XDIST_WORKER_COUNT", "0"))


def get_cpu_architecture() -> Literal["x86_64", "arm", "unknown"]:
    """Detects the CPU architecture.

    This function utilizes Python's `platform` module to reliably determine
    if the program is running on an x86-64 (also known as AMD64) or an ARM
    (including aarch64/arm64) CPU architecture. It aims to be compatible
    across all operating systems supported by Python (Windows, Linux, macOS).

    Returns:
        Literal['x86_64', 'arm', 'unknown']: A string representing the
        detected architecture. It returns 'x86_64' for 64-bit x86
        processors, 'arm' for ARM-based processors (both 32-bit and 64-bit),
        and 'unknown' if the architecture is neither or cannot be
        confidently determined.

    Examples:
        >>> # On an Intel-based Mac or typical Linux/Windows PC:
        >>> # get_cpu_architecture()
        'x86_64'
        >>> # On an Apple Silicon Mac or Raspberry Pi 4:
        >>> # get_cpu_architecture()
        'arm'
    """
    machine: str = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine.startswith(("arm", "aarch")):
        return "arm"
    # Add checks for other potential identifiers if needed, though
    # the above cover the vast majority of cases for these two archs.
    # Consider checking platform.processor() as a fallback
    # or other system-specific methods if higher reliability
    # on obscure platforms is required. For most uses,
    # platform.machine() is sufficient and standard.
    return "unknown"
