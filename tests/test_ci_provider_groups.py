"""Unit tests for diff-aware CI provider selection, image pulling, and required-job gates."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest

from scripts.ci.check_required_jobs import evaluate_required_jobs
from scripts.ci.pull_images import UnknownProviderError, pull_provider_images
from scripts.ci.run_tests import build_compatibility_command, build_provider_command
from scripts.ci.select_provider_tests import (
    PROJECT_ROOT,
    ManifestValidationError,
    load_manifest,
    parse_name_status,
    render_summary,
    select_providers,
    validate_manifest,
    write_github_outputs,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_live_manifest_validates_against_repository_inventory() -> None:
    """Verify .github/ci/provider-groups.json matches the repository source and test tree."""
    manifest = load_manifest()
    validate_manifest(manifest, project_root=PROJECT_ROOT)
    assert manifest["supported_python_versions"] == ["3.11", "3.12", "3.13", "3.14", "3.15"]
    assert manifest["providers"]["minio"]["images"] == [
        "cgr.dev/chainguard/minio-client:latest",
        "cgr.dev/chainguard/minio:latest",
    ]


def test_validate_manifest_rejects_invalid_schema_and_unsafe_paths() -> None:
    """Verify validate_manifest rejects schema drift, Python version drift, and traversal paths."""
    base = load_manifest()

    bad_schema = copy.deepcopy(base)
    bad_schema["schema_version"] = 2
    with pytest.raises(ManifestValidationError, match="unsupported schema_version"):
        validate_manifest(bad_schema, project_root=PROJECT_ROOT)

    bad_py = copy.deepcopy(base)
    bad_py["supported_python_versions"] = ["3.9", "3.10"]
    with pytest.raises(ManifestValidationError, match="supported_python_versions"):
        validate_manifest(bad_py, project_root=PROJECT_ROOT)

    unsafe_path = copy.deepcopy(base)
    unsafe_path["provider_scoped_dependency_paths"] = ["../outside.toml"]
    with pytest.raises(ManifestValidationError, match="unsafe path"):
        validate_manifest(unsafe_path, project_root=PROJECT_ROOT)


def test_select_providers_single_provider_change() -> None:
    """Verify changing a single provider module selects only that provider on Python 3.12."""
    manifest = load_manifest()
    selection = select_providers(manifest, ["src/pytest_databases/docker/minio.py"])

    assert selection["mode"] == "selective"
    assert selection["providers"] == ["minio"]
    assert selection["provider_job_count"] == 1
    assert selection["image_pull_count"] == 2
    assert selection["images"] == [
        "cgr.dev/chainguard/minio-client:latest",
        "cgr.dev/chainguard/minio:latest",
    ]
    assert selection["provider_matrix"] == {
        "include": [
            {
                "provider": "minio",
                "python-version": "3.12",
                "test_paths": ["tests/test_minio.py"],
            }
        ]
    }
    assert selection["run_compatibility"] is True
    assert selection["run_docs"] is False
    assert selection["run_quality"] is True


def test_select_providers_docs_only_change() -> None:
    """Verify docs-only changes build docs without pulling images or running provider jobs."""
    manifest = load_manifest()
    selection = select_providers(manifest, ["docs/supported-databases/minio.rst"])

    assert selection["mode"] == "docs-only"
    assert selection["providers"] == []
    assert selection["provider_job_count"] == 0
    assert selection["image_pull_count"] == 0
    assert selection["run_docs"] is True
    assert selection["run_compatibility"] is False
    assert selection["run_quality"] is False


def test_select_providers_metadata_only_change() -> None:
    """Verify metadata and CI unit test changes run quality checks without starting containers."""
    manifest = load_manifest()
    selection = select_providers(manifest, [".pre-commit-config.yaml", "tests/test_ci_provider_groups.py"])

    assert selection["mode"] == "metadata-only"
    assert selection["providers"] == []
    assert selection["provider_job_count"] == 0
    assert selection["run_quality"] is True
    assert selection["run_docs"] is False
    assert selection["run_compatibility"] is False


def test_select_providers_shared_runtime_and_full_matrix() -> None:
    """Verify shared runtime changes select all providers on 3.12 and full=True expands 3.11-3.15."""
    manifest = load_manifest()
    all_providers = sorted(manifest["providers"])

    shared_selection = select_providers(manifest, ["src/pytest_databases/_service.py"])
    assert shared_selection["mode"] == "all-providers"
    assert shared_selection["providers"] == all_providers
    assert shared_selection["provider_job_count"] == len(all_providers)

    full_selection = select_providers(manifest, ["src/pytest_databases/docker/minio.py"], full=True)
    assert full_selection["mode"] == "full"
    assert full_selection["providers"] == all_providers
    assert full_selection["provider_job_count"] == len(all_providers) * 5
    assert full_selection["run_docs"] is True


def test_select_providers_fail_closed_and_dependency_scoping() -> None:
    """Verify unknown paths fail closed while single-provider dependency changes stay scoped."""
    manifest = load_manifest()
    all_providers = sorted(manifest["providers"])

    unknown = select_providers(manifest, ["src/pytest_databases/unmapped_module.py"])
    assert unknown["mode"] == "fail-closed"
    assert unknown["providers"] == all_providers

    scoped_dep = select_providers(manifest, ["pyproject.toml", "src/pytest_databases/docker/minio.py"])
    assert scoped_dep["mode"] == "selective"
    assert scoped_dep["providers"] == ["minio"]

    global_dep = select_providers(manifest, ["pyproject.toml"])
    assert global_dep["mode"] == "all-providers"
    assert global_dep["providers"] == all_providers


def test_parse_name_status_and_output_rendering(tmp_path: Path) -> None:
    """Verify NUL-delimited git diff parsing, GitHub output writing, and summary rendering."""
    raw = b"M\x00src/pytest_databases/docker/minio.py\x00R100\x00old/path.py\x00new/path.py\x00"
    assert parse_name_status(raw) == [
        "src/pytest_databases/docker/minio.py",
        "old/path.py",
        "new/path.py",
    ]

    manifest = load_manifest()
    selection = select_providers(manifest, ["src/pytest_databases/docker/minio.py"])
    output_file = tmp_path / "github_output.txt"
    write_github_outputs(output_file, selection)
    content = output_file.read_text(encoding="utf-8")
    assert "mode=selective\n" in content
    assert 'providers=["minio"]\n' in content
    assert "run_provider_tests=true\n" in content

    summary = render_summary(selection)
    assert "## Provider-aware CI selection" in summary
    assert "`cgr.dev/chainguard/minio:latest`" in summary


def test_pull_provider_images_retries_and_reports_failures() -> None:
    """Verify pull_provider_images retries transient failures and raises on unknown providers."""
    manifest = load_manifest()
    call_counts: dict[str, int] = {}
    sleeps: list[float] = []

    def flaky_runner(command: list[str]) -> bool:
        image = command[-1]
        call_counts[image] = call_counts.get(image, 0) + 1
        return call_counts[image] >= 2

    failures = pull_provider_images(
        manifest,
        "minio",
        run_command=flaky_runner,
        sleep=sleeps.append,
        attempts=3,
    )
    assert failures == []
    assert sleeps == [5.0, 5.0]

    with pytest.raises(UnknownProviderError, match="unknown provider"):
        pull_provider_images(manifest, "nonexistent", run_command=flaky_runner)


def test_build_commands_and_evaluate_required_jobs() -> None:
    """Verify pytest command construction and required-job status evaluation."""
    manifest = load_manifest()
    compat_cmd = build_compatibility_command(manifest)
    assert compat_cmd[1:3] == ["-m", "pytest"]
    assert "tests/test_valkey.py::test_plugin_imports_without_valkey" in compat_cmd

    provider_cmd = build_provider_command(manifest, "minio", coverage=True)
    assert "--cov=pytest_databases" in provider_cmd
    assert provider_cmd[-1] == "tests/test_minio.py"

    ok_failures = evaluate_required_jobs(
        {
            "select": "success",
            "quality": "success",
            "compatibility": "skipped",
            "docs": "success",
            "provider": "skipped",
            "coverage": "skipped",
        },
        expected={
            "quality": True,
            "compatibility": False,
            "docs": True,
            "provider": False,
            "coverage": False,
        },
    )
    assert ok_failures == []

    bad_failures = evaluate_required_jobs(
        {
            "select": "success",
            "quality": "success",
            "compatibility": "skipped",
            "docs": "failure",
            "provider": "skipped",
            "coverage": "skipped",
        },
        expected={
            "quality": True,
            "compatibility": True,
            "docs": True,
            "provider": False,
            "coverage": False,
        },
    )
    assert bad_failures == [
        "compatibility was skipped but selection required it",
        "docs was failure",
    ]
