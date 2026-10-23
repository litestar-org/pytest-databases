"""Select the smallest safe provider test scope for a Git diff.

Git is invoked exclusively with a resolved executable and fixed argument vector.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

PROJECT_ROOT = Path(__file__).parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / ".github" / "ci" / "provider-groups.json"
MANIFEST_REPOSITORY_PATH = ".github/ci/provider-groups.json"
GIT_EXECUTABLE = shutil.which("git")
PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SUPPORTED_CI_PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14", "3.15"]


class ManifestValidationError(ValueError):
    """Raised when provider ownership does not match the repository."""


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load the provider ownership manifest."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT) -> None:
    """Reject manifest schema, ownership, and repository inventory drift."""
    if manifest.get("schema_version") != 1:
        message = f"unsupported schema_version: {manifest.get('schema_version')!r}"
        raise ManifestValidationError(message)
    python_versions = manifest.get("supported_python_versions")
    if python_versions != SUPPORTED_CI_PYTHON_VERSIONS:
        message = "supported_python_versions must match the declared Python 3.11-3.15 CI matrix range"
        raise ManifestValidationError(message)
    providers = manifest.get("providers")
    if not isinstance(providers, Mapping) or not providers:
        message = "providers must be a non-empty mapping"
        raise ManifestValidationError(message)
    if (
        not isinstance(manifest.get("provider_scoped_dependency_paths"), list)
        or not manifest["provider_scoped_dependency_paths"]
    ):
        message = "provider_scoped_dependency_paths must be a non-empty list"
        raise ManifestValidationError(message)
    for path in manifest["provider_scoped_dependency_paths"]:
        _validate_relative_path(path)

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

    for label, values in (("source", owned_sources), ("test", owned_tests)):
        duplicates = sorted({path for path in values if values.count(path) > 1})
        if duplicates:
            message = f"duplicate {label} ownership: {', '.join(duplicates)}"
            raise ManifestValidationError(message)

    discovered_sources, discovered_tests = _discover_provider_files(project_root)
    for label, owned_set, discovered_set in (
        ("source", set(owned_sources), discovered_sources),
        ("test", set(owned_tests), discovered_tests),
    ):
        missing = sorted(discovered_set - owned_set)
        if missing:
            message = f"unowned provider {label}: {', '.join(missing)}"
            raise ManifestValidationError(message)
        extra = sorted(owned_set - discovered_set)
        if extra:
            message = f"missing provider {label} path: {', '.join(extra)}"
            raise ManifestValidationError(message)

    for path in manifest.get("compatibility_test_paths", []):
        _validate_relative_path(path)
        file_path = path.split("::", maxsplit=1)[0]
        if not (project_root / file_path).is_file():
            message = f"missing compatibility test path: {file_path}"
            raise ManifestValidationError(message)

    _validate_tracked_coverage(manifest, project_root)


def build_matrix(manifest: Mapping[str, Any], provider_ids: Sequence[str], *, full: bool) -> dict[str, Any]:
    """Build selective or full provider/Python matrix cells."""
    providers = manifest["providers"]
    python_versions = manifest["supported_python_versions"] if full else ["3.12"]
    return {
        "include": [
            {
                "provider": provider_id,
                "python-version": python_version,
                "test_paths": providers[provider_id]["test_paths"],
            }
            for provider_id in provider_ids
            for python_version in python_versions
        ]
    }


def select_providers(
    manifest: Mapping[str, Any],
    changed_paths: Sequence[str],
    *,
    full: bool = False,
    full_reason: str | None = None,
    manifest_provider_ids: Sequence[str] | None = (),
) -> dict[str, Any]:
    """Map changed paths to provider groups, failing closed for unknown paths."""
    paths = _deduplicate(normalized for path in changed_paths if (normalized := _normalize_changed_path(path)))
    providers = manifest["providers"]
    all_provider_ids = sorted(providers)
    dependency_paths = {path for path in paths if _matches(path, manifest["provider_scoped_dependency_paths"])}

    if full:
        selected_ids = all_provider_ids
        mode = "full"
        reason = full_reason or "full execution was explicitly requested"
    elif not paths:
        selected_ids = all_provider_ids
        mode = "fail-closed"
        reason = "no usable changed paths were available"
    elif all(
        _matches(path, manifest["docs_only_globs"]) or _matches(path, manifest["metadata_only_globs"]) for path in paths
    ):
        selected_ids = []
        if any(_matches(path, manifest["metadata_only_globs"]) for path in paths):
            mode = "metadata-only"
            reason = "changed paths are allowlisted metadata and require quality checks only"
        else:
            mode = "docs-only"
            reason = "all changed paths are documentation"
    elif MANIFEST_REPOSITORY_PATH in paths and manifest_provider_ids is None:
        selected_ids = all_provider_ids
        mode = "all-providers"
        reason = "shared provider manifest settings changed"
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
        selected.update(manifest_provider_ids or ())
        known_paths = {
            path
            for path in paths
            if any(
                _matches(path, [*provider["source_globs"], *provider["test_paths"], *provider["docs_globs"]])
                for provider in providers.values()
            )
            or path == MANIFEST_REPOSITORY_PATH
            or _matches(path, manifest["docs_only_globs"])
            or _matches(path, manifest["metadata_only_globs"])
        }
        unknown_paths = sorted(set(paths) - known_paths)
        unknown_paths = [
            path for path in unknown_paths if not _matches(path, manifest["provider_scoped_dependency_paths"])
        ]
        if unknown_paths:
            selected_ids = all_provider_ids
            mode = "fail-closed"
            reason = f"unknown runtime-impacting paths changed: {', '.join(unknown_paths)}"
        elif dependency_paths and len(selected) != 1:
            selected_ids = all_provider_ids
            mode = "all-providers"
            reason = "dependency metadata changed without exactly one provider owner"
        else:
            selected_ids = sorted(selected)
            mode = "selective"
            reason = f"selected providers owning changed paths: {', '.join(selected_ids)}"

    images = sorted({image for provider_id in selected_ids for image in providers[provider_id]["images"]})
    provider_images = {provider_id: providers[provider_id]["images"] for provider_id in selected_ids}
    test_paths = sorted({path for provider_id in selected_ids for path in providers[provider_id]["test_paths"]})
    matrix = build_matrix(manifest, selected_ids, full=full)
    run_docs = full or any(_matches(path, manifest["docs_only_globs"]) for path in paths)
    return {
        "mode": mode,
        "reason": reason,
        "changed_paths": paths,
        "providers": selected_ids,
        "images": images,
        "provider_images": provider_images,
        "test_paths": test_paths,
        "provider_matrix": matrix,
        "provider_job_count": len(matrix["include"]),
        "image_pull_count": sum(len(providers[cell["provider"]]["images"]) for cell in matrix["include"]),
        "compatibility_test_paths": manifest["compatibility_test_paths"],
        "run_compatibility": bool(selected_ids),
        "run_docs": run_docs,
        "run_quality": bool(selected_ids) or mode == "metadata-only",
    }


def changed_manifest_provider_ids(
    base_ref: str, manifest: Mapping[str, Any], *, cwd: Path = PROJECT_ROOT
) -> list[str] | None:
    """Return provider entries changed from the base, or ``None`` for shared schema changes."""
    if GIT_EXECUTABLE is None:
        message = "git executable was not found"
        raise RuntimeError(message)
    result = subprocess.run(
        [GIT_EXECUTABLE, "show", f"{base_ref}:{MANIFEST_REPOSITORY_PATH}"],
        cwd=cwd,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    base_manifest = json.loads(result.stdout)
    provider_scoped_keys = {"providers", "compatibility_test_paths"}
    base_shared = {key: value for key, value in base_manifest.items() if key not in provider_scoped_keys}
    head_shared = {key: value for key, value in manifest.items() if key not in provider_scoped_keys}
    if base_shared != head_shared:
        return None
    base_providers = base_manifest.get("providers", {})
    head_providers = manifest["providers"]
    changed = sorted(
        provider_id
        for provider_id in set(base_providers) | set(head_providers)
        if base_providers.get(provider_id) != head_providers.get(provider_id)
    )
    if any(provider_id not in head_providers for provider_id in changed):
        return None
    base_compatibility = set(base_manifest.get("compatibility_test_paths", []))
    head_compatibility = set(manifest.get("compatibility_test_paths", []))
    if base_compatibility - head_compatibility:
        return None
    changed_provider_ids = set(changed)
    for compatibility_path in head_compatibility - base_compatibility:
        test_file = compatibility_path.split("::", maxsplit=1)[0]
        owners = {
            provider_id for provider_id, provider in head_providers.items() if test_file in provider["test_paths"]
        }
        if len(owners) != 1:
            return None
        changed_provider_ids.update(owners)
    return sorted(changed_provider_ids)


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
        [GIT_EXECUTABLE, "diff", "--name-status", "-z", "-M", f"{base}...{head}"],
        cwd=cwd,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
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
        "run_compatibility": str(selection["run_compatibility"]).lower(),
        "run_docs": str(selection["run_docs"]).lower(),
        "run_quality": str(selection["run_quality"]).lower(),
        "mode": selection["mode"],
    }
    with path.open("a", encoding="utf-8") as output_file:
        for key, value in outputs.items():
            output_file.write(f"{key}={value}\n")


def render_summary(selection: Mapping[str, Any]) -> str:
    """Render a concise selection audit for the workflow summary."""
    providers = ", ".join(selection["providers"]) or "none"
    changed_paths = "\n".join(f"- `{path}`" for path in selection["changed_paths"]) or "- none"
    test_paths = "\n".join(f"- `{path}`" for path in selection["test_paths"]) or "- none"
    images = "\n".join(f"- `{image}`" for image in selection["images"]) or "- none"
    provider_images = (
        "\n".join(
            f"- **{provider_id}**: {', '.join(f'`{image}`' for image in owned_images)}"
            for provider_id, owned_images in selection["provider_images"].items()
        )
        or "- none"
    )
    return "\n".join([
        "## Provider-aware CI selection",
        "",
        f"- Mode: `{selection['mode']}`",
        f"- Providers: {providers}",
        f"- Provider jobs: {selection['provider_job_count']}",
        f"- Image pulls: {selection['image_pull_count']}",
        f"- Reason: {selection['reason']}",
        f"- Event: `{selection.get('event_name', 'local')}`",
        f"- Base: `{selection.get('base_ref') or 'not available'}`",
        f"- Head: `{selection.get('head_ref') or 'not available'}`",
        "",
        "### Changed paths",
        "",
        changed_paths,
        "",
        "### Selected tests",
        "",
        test_paths,
        "",
        "### Required images",
        "",
        images,
        "",
        "### Images by provider",
        "",
        provider_images,
        "",
        "### Cost budgets",
        "",
        "| Scenario | Provider jobs | Image pulls |",
        "| --- | ---: | ---: |",
        "| Legacy eager PR baseline | 19 | about 540 |",
        "| Docs-only target | 0 | 0 |",
        "| Single-provider target | 1 | provider-owned only |",
        "| Shared runtime target | 19 | 53 |",
        "| Nightly/manual full target | 95 | 265 |",
        "",
        "Add or remove the `ci:full` label to request or cancel a full pull-request matrix.",
    ])


def main(argv: Sequence[str] | None = None) -> int:
    """Run provider selection and emit JSON plus optional Actions outputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--full-reason")
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

    manifest_provider_ids: Sequence[str] | None = ()
    if MANIFEST_REPOSITORY_PATH in changed_paths:
        manifest_provider_ids = (
            changed_manifest_provider_ids(args.base_ref, manifest) if args.base_ref is not None else None
        )
    selection = select_providers(
        manifest,
        changed_paths,
        full=args.full,
        full_reason=args.full_reason,
        manifest_provider_ids=manifest_provider_ids,
    )
    selection["event_name"] = os.environ.get("GITHUB_EVENT_NAME", "local")
    selection["base_ref"] = args.base_ref
    selection["head_ref"] = args.head_ref
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


def _validate_relative_path(path: str) -> None:
    candidate = Path(path.split("::", maxsplit=1)[0])
    if candidate.is_absolute() or ".." in candidate.parts:
        message = f"unsafe path in provider manifest: {path}"
        raise ManifestValidationError(message)


def _discover_provider_files(project_root: Path) -> tuple[set[str], set[str]]:
    sources = {
        path.relative_to(project_root).as_posix()
        for path in (project_root / "src" / "pytest_databases" / "docker").glob("*.py")
        if path.name != "__init__.py"
    }
    sources.add("src/pytest_databases/_service.py")
    if (project_root / ".github" / "workflows" / "ci.yaml").is_file():
        sources.add(".github/workflows/ci.yaml")
    sources.update(path.relative_to(project_root).as_posix() for path in (project_root / "scripts" / "ci").glob("*.py"))
    tests = {
        path.relative_to(project_root).as_posix()
        for path in (project_root / "tests").glob("test_*.py")
        if not path.name.startswith("test_ci_")
    }
    return sources, tests


def _validate_tracked_coverage(manifest: Mapping[str, Any], project_root: Path) -> None:
    coverage_patterns = _manifest_coverage_patterns(manifest)
    unmapped_tracked = sorted(
        path for path in _tracked_repository_files(project_root) if not _matches(path, coverage_patterns)
    )
    if unmapped_tracked:
        message = f"unmapped tracked repository files: {', '.join(unmapped_tracked)}"
        raise ManifestValidationError(message)


def _manifest_coverage_patterns(manifest: Mapping[str, Any]) -> list[str]:
    patterns = [
        MANIFEST_REPOSITORY_PATH,
        *manifest.get("shared_all_provider_paths", ()),
        *manifest.get("provider_scoped_dependency_paths", ()),
        *manifest.get("docs_only_globs", ()),
        *manifest.get("metadata_only_globs", ()),
    ]
    for provider in manifest["providers"].values():
        patterns.extend(provider["source_globs"])
        patterns.extend(provider["test_paths"])
        patterns.extend(provider["docs_globs"])
    return _deduplicate(patterns)


def _tracked_repository_files(project_root: Path) -> list[str]:
    if GIT_EXECUTABLE is None:
        return []
    result = subprocess.run(
        [GIT_EXECUTABLE, "ls-files", "-z"],
        cwd=project_root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    return [path for path in result.stdout.decode().split("\0") if path]


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _deduplicate(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize_changed_path(path: str) -> str:
    normalized = path.strip("/")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        message = f"changed path contains control characters: {path!r}"
        raise ValueError(message)
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
