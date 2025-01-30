from __future__ import annotations

import hashlib
import os


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
