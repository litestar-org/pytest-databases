"""Select the smallest safe provider test scope for a Git diff."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess  # noqa: S404 - Git is invoked with a fixed executable and argv.
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

PROJECT_ROOT = Path(__file__).parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / ".github" / "ci" / "provider-groups.json"
GIT_EXECUTABLE = shutil.which("git")
PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ManifestValidationError(ValueError):
    """Raised when provider ownership does not match the repository."""


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load the provider ownership manifest."""
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_relative_path(path: str) -> None:
    candidate = Path(path.split("::", maxsplit=1)[0])
    if candidate.is_absolute() or ".." in candidate.parts:
        message = f"unsafe path in provider manifest: {path}"
        raise ManifestValidationError(message)


def validate_manifest(manifest: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT) -> None:
    """Reject manifest schema, ownership, and repository inventory drift."""
    if manifest.get("schema_version") != 1:
        message = f"unsupported schema_version: {manifest.get('schema_version')!r}"
        raise ManifestValidationError(message)
    providers = manifest.get("providers")
    if not isinstance(providers, Mapping) or not providers:
        message = "providers must be a non-empty mapping"
        raise ManifestValidationError(message)

    owned_sources: list[str] = []
    owned_tests: list[str] = []
    for provider_id, provider in providers.items():
        if not isinstance(provider_id, str) or PROVIDER_ID_PATTERN.fullmatch(provider_id) is None:
            message = f"invalid provider ID: {provider_id!r}"
            raise ManifestValidationError(message)
        if not isinstance(provider, Mapping):
            message = f"provider {provider_id} must be a mapping"
            raise ManifestValidationError(message)
        for key in ("source_globs", "test_paths", "images", "docs_globs"):
            values = provider.get(key)
            if not isinstance(values, list) or not values or not all(isinstance(value, str) for value in values):
                if key == "images":
                    message = f"provider {provider_id} must own at least one image"
                else:
                    message = f"provider {provider_id} must define non-empty {key}"
                raise ManifestValidationError(message)
            for value in values:
                _validate_relative_path(value)
        owned_sources.extend(provider["source_globs"])
        owned_tests.extend(provider["test_paths"])

    duplicate_sources = sorted(path for path in set(owned_sources) if owned_sources.count(path) > 1)
    duplicate_tests = sorted(path for path in set(owned_tests) if owned_tests.count(path) > 1)
    if duplicate_sources:
        message = f"duplicate source ownership: {', '.join(duplicate_sources)}"
        raise ManifestValidationError(message)
    if duplicate_tests:
        message = f"duplicate test ownership: {', '.join(duplicate_tests)}"
        raise ManifestValidationError(message)

    discovered_sources = {
        path.relative_to(project_root).as_posix()
        for path in (project_root / "src" / "pytest_databases" / "docker").glob("*.py")
        if path.name != "__init__.py"
    }
    discovered_sources.add("src/pytest_databases/_service.py")
    discovered_tests = {
        path.relative_to(project_root).as_posix()
        for path in (project_root / "tests").glob("test_*.py")
        if not path.name.startswith("test_ci_")
    }
    missing_sources = sorted(discovered_sources - set(owned_sources))
    extra_sources = sorted(set(owned_sources) - discovered_sources)
    missing_tests = sorted(discovered_tests - set(owned_tests))
    extra_tests = sorted(set(owned_tests) - discovered_tests)
    if missing_sources:
        message = f"unowned provider source: {', '.join(missing_sources)}"
        raise ManifestValidationError(message)
    if extra_sources:
        message = f"missing provider source path: {', '.join(extra_sources)}"
        raise ManifestValidationError(message)
    if missing_tests:
        message = f"unowned provider test: {', '.join(missing_tests)}"
        raise ManifestValidationError(message)
    if extra_tests:
        message = f"missing provider test path: {', '.join(extra_tests)}"
        raise ManifestValidationError(message)

    for path in manifest.get("compatibility_test_paths", []):
        _validate_relative_path(path)
        file_path = path.split("::", maxsplit=1)[0]
        if not (project_root / file_path).is_file():
            message = f"missing compatibility test path: {file_path}"
            raise ManifestValidationError(message)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _deduplicate(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def select_providers(
    manifest: Mapping[str, Any], changed_paths: Sequence[str], *, full: bool = False
) -> dict[str, Any]:
    """Map changed paths to provider groups, failing closed for unknown paths."""
    paths = _deduplicate(path.strip("/") for path in changed_paths if path.strip("/"))
    providers = manifest["providers"]
    all_provider_ids = sorted(providers)

    if full:
        selected_ids = all_provider_ids
        mode = "full"
        reason = "full execution was explicitly requested"
    elif not paths:
        selected_ids = all_provider_ids
        mode = "fail-closed"
        reason = "no usable changed paths were available"
    elif all(
        _matches(path, manifest["docs_only_globs"]) or _matches(path, manifest["metadata_only_globs"]) for path in paths
    ):
        selected_ids = []
        mode = "docs-only"
        reason = "all changed paths are documentation or allowlisted metadata"
    elif any(_matches(path, manifest["shared_all_provider_paths"]) for path in paths):
        selected_ids = all_provider_ids
        mode = "all-providers"
        reason = "a shared runtime, dependency, or CI path changed"
    else:
        selected = {
            provider_id
            for provider_id, provider in providers.items()
            if any(_matches(path, [*provider["source_globs"], *provider["test_paths"]]) for path in paths)
        }
        known_paths = {
            path
            for path in paths
            if any(
                _matches(path, [*provider["source_globs"], *provider["test_paths"], *provider["docs_globs"]])
                for provider in providers.values()
            )
            or _matches(path, manifest["docs_only_globs"])
            or _matches(path, manifest["metadata_only_globs"])
        }
        unknown_paths = sorted(set(paths) - known_paths)
        if unknown_paths:
            selected_ids = all_provider_ids
            mode = "fail-closed"
            reason = f"unknown runtime-impacting paths changed: {', '.join(unknown_paths)}"
        else:
            selected_ids = sorted(selected)
            mode = "selective"
            reason = f"selected providers owning changed paths: {', '.join(selected_ids)}"

    images = sorted({image for provider_id in selected_ids for image in providers[provider_id]["images"]})
    matrix = {
        "include": [
            {
                "provider": provider_id,
                "test_paths": providers[provider_id]["test_paths"],
            }
            for provider_id in selected_ids
        ]
    }
    return {
        "mode": mode,
        "reason": reason,
        "changed_paths": paths,
        "providers": selected_ids,
        "images": images,
        "provider_matrix": matrix,
        "compatibility_test_paths": manifest["compatibility_test_paths"],
    }


def parse_name_status(output: bytes) -> list[str]:
    """Return old and new paths from NUL-delimited ``git diff --name-status`` output."""
    fields = output.decode().split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        status, separator, first_path = field.partition("\t")
        if not separator:
            status = field
            if index >= len(fields) or not fields[index]:
                message = f"Missing path for git diff record: {field!r}"
                raise ValueError(message)
            first_path = fields[index]
            index += 1
        paths.append(first_path)
        if status.startswith(("R", "C")):
            if index >= len(fields) or not fields[index]:
                message = f"Missing destination path for git diff record: {field!r}"
                raise ValueError(message)
            paths.append(fields[index])
            index += 1
    return _deduplicate(paths)


def changed_files_for_range(base: str, head: str, *, cwd: Path = PROJECT_ROOT) -> list[str]:
    """Read changed paths for a Git range, retaining both sides of renames."""
    if GIT_EXECUTABLE is None:
        message = "git executable was not found"
        raise RuntimeError(message)
    result = subprocess.run(
        [GIT_EXECUTABLE, "diff", "--name-status", "-z", "-M", base, head],
        cwd=cwd,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return parse_name_status(result.stdout)


def write_github_outputs(path: Path, selection: Mapping[str, Any]) -> None:
    """Write compact, single-line values to a GitHub Actions output file."""
    outputs = {
        "matrix": json.dumps(selection["provider_matrix"], separators=(",", ":")),
        "providers": json.dumps(selection["providers"], separators=(",", ":")),
        "run_provider_tests": str(bool(selection["providers"])).lower(),
        "mode": selection["mode"],
        "reason": selection["reason"],
    }
    with path.open("a", encoding="utf-8") as output_file:
        for key, value in outputs.items():
            output_file.write(f"{key}={value}\n")


def render_summary(selection: Mapping[str, Any]) -> str:
    """Render a concise selection audit for the workflow summary."""
    providers = ", ".join(selection["providers"]) or "none"
    return "\n".join([
        "## Provider-aware CI selection",
        "",
        f"- Mode: `{selection['mode']}`",
        f"- Providers: {providers}",
        f"- Images: {len(selection['images'])}",
        f"- Reason: {selection['reason']}",
    ])


def main(argv: Sequence[str] | None = None) -> int:
    """Run provider selection and emit JSON plus optional Actions outputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    validate_manifest(manifest, project_root=PROJECT_ROOT)

    changed_paths = args.changed_file
    if args.base_ref or args.head_ref:
        if not args.base_ref or not args.head_ref:
            parser.error("--base-ref and --head-ref must be provided together")
        changed_paths = changed_files_for_range(args.base_ref, args.head_ref)

    selection = select_providers(manifest, changed_paths, full=args.full)
    sys.stdout.write(f"{json.dumps(selection, indent=2, sort_keys=True)}\n")
    output_path = args.github_output or (Path(os.environ["GITHUB_OUTPUT"]) if "GITHUB_OUTPUT" in os.environ else None)
    if output_path is not None:
        write_github_outputs(output_path, selection)
    summary_path = args.summary or (
        Path(os.environ["GITHUB_STEP_SUMMARY"]) if "GITHUB_STEP_SUMMARY" in os.environ else None
    )
    if summary_path is not None:
        with summary_path.open("a", encoding="utf-8") as summary_file:
            summary_file.write(f"{render_summary(selection)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
