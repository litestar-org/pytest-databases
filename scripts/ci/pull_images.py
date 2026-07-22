"""Pull exactly one manifest-owned provider image set with bounded retries."""

from __future__ import annotations

import argparse
import shutil
import subprocess  # noqa: S404 - Docker is invoked with a fixed executable and argv.
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from scripts.ci.select_provider_tests import load_manifest, validate_manifest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Any


class UnknownProviderError(ValueError):
    """Raised when a provider ID is absent from the validated manifest."""


def _default_run_command(command: list[str]) -> bool:
    return subprocess.run(command, check=False, timeout=600).returncode == 0


def pull_provider_images(
    manifest: Mapping[str, Any],
    provider_id: str,
    *,
    run_command: Callable[[list[str]], bool] = _default_run_command,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 5,
    workers: int = 4,
    docker_executable: str = "docker",
) -> list[str]:
    """Pull a provider's images and return any terminal failures."""
    providers = manifest["providers"]
    if provider_id not in providers:
        message = f"unknown provider: {provider_id}"
        raise UnknownProviderError(message)
    if attempts < 1:
        message = "attempts must be at least one"
        raise ValueError(message)

    def pull(image: str) -> str | None:
        for attempt in range(1, attempts + 1):
            if run_command([docker_executable, "pull", image]):
                return None
            if attempt < attempts:
                sleep(float(attempt * attempt * 5))
        return image

    images = providers[provider_id]["images"]
    with ThreadPoolExecutor(max_workers=min(workers, len(images))) as executor:
        return sorted(failure for failure in executor.map(pull, images) if failure is not None)


def main(argv: Sequence[str] | None = None) -> int:
    """Pull images for one validated provider ID."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    docker_executable = shutil.which("docker")
    if docker_executable is None:
        sys.stderr.write("docker executable was not found\n")
        return 2
    manifest = load_manifest()
    validate_manifest(manifest)
    try:
        failures = pull_provider_images(
            manifest,
            args.provider,
            workers=args.workers,
            docker_executable=docker_executable,
        )
    except UnknownProviderError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    if failures:
        sys.stderr.write(f"failed to pull required images: {', '.join(failures)}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
