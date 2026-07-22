"""Run manifest-owned pytest nodes without shell interpolation."""

from __future__ import annotations

import argparse
import subprocess  # noqa: S404 - test commands use the current interpreter and fixed argv.
import sys
from typing import TYPE_CHECKING

from scripts.ci.select_provider_tests import load_manifest, validate_manifest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any


def build_compatibility_command(manifest: Mapping[str, Any]) -> list[str]:
    """Build the engine-free compatibility pytest command."""
    return [sys.executable, "-m", "pytest", *manifest["compatibility_test_paths"]]


def main(argv: Sequence[str] | None = None) -> int:
    """Run a validated manifest test scope."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--compatibility", action="store_true")
    args = parser.parse_args(argv)
    if not args.compatibility:
        parser.error("one test scope must be selected")

    manifest = load_manifest()
    validate_manifest(manifest)
    result = subprocess.run(build_compatibility_command(manifest), check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
