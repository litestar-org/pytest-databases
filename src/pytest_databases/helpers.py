from __future__ import annotations

import hashlib


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
