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


def build_provider_command(manifest: Mapping[str, Any], provider_id: str, *, coverage: bool = False) -> list[str]:
    """Build a pytest command for exactly one validated provider group."""
    providers = manifest["providers"]
    if provider_id not in providers:
        message = f"unknown provider: {provider_id}"
        raise ValueError(message)
    coverage_args = ["--cov=pytest_databases", "--cov-report="] if coverage else []
    return [sys.executable, "-m", "pytest", *coverage_args, *providers[provider_id]["test_paths"]]


def main(argv: Sequence[str] | None = None) -> int:
    """Run a validated manifest test scope."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--compatibility", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args(argv)
    if args.compatibility == bool(args.provider):
        parser.error("select exactly one of --compatibility or --provider")

    manifest = load_manifest()
    validate_manifest(manifest)
    command = (
        build_compatibility_command(manifest)
        if args.compatibility
        else build_provider_command(manifest, args.provider, coverage=args.coverage)
    )
    result = subprocess.run(command, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
