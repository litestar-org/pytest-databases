"""Unit tests for diff-aware CI provider selection, image pulling, and required-job gates."""

from __future__ import annotations

import copy
import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from scripts.ci import select_provider_tests
from scripts.ci.check_required_jobs import evaluate_required_jobs
from scripts.ci.pull_images import UnknownProviderError, pull_provider_images
from scripts.ci.run_tests import build_compatibility_command, build_provider_command
from scripts.ci.select_provider_tests import (
    GIT_EXECUTABLE,
    MANIFEST_REPOSITORY_PATH,
    PROJECT_ROOT,
    ManifestValidationError,
    changed_files_for_range,
    changed_manifest_provider_ids,
    load_manifest,
    parse_name_status,
    render_summary,
    select_providers,
    validate_manifest,
    write_github_outputs,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from typing import Any


_DEFAULT_COMPATIBILITY_PATHS = [
    "tests/test_minio.py::test_plugin_imports_without_minio",
    "tests/test_postgres.py::test_plugin_imports_without_psycopg",
]


def test_live_manifest_validates_against_repository_inventory() -> None:
    """Verify .github/ci/provider-groups.json matches the repository source and test tree."""
    manifest = load_manifest()
    validate_manifest(manifest, project_root=PROJECT_ROOT)
    assert manifest["supported_python_versions"] == ["3.11", "3.12", "3.13", "3.14", "3.15"]
    assert manifest["providers"]["minio"]["images"] == ["cgr.dev/chainguard/minio:latest"]
    assert manifest["providers"]["spanner"]["images"] == ["gcr.io/cloud-spanner-emulator/emulator:latest"]


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
    assert selection["image_pull_count"] == 1
    assert selection["images"] == ["cgr.dev/chainguard/minio:latest"]
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
    """Verify metadata, Makefile, and CI unit test changes run quality checks without starting containers."""
    manifest = load_manifest()
    selection = select_providers(
        manifest,
        [".pre-commit-config.yaml", "Makefile", "tests/test_ci_provider_groups.py"],
    )

    assert selection["mode"] == "metadata-only"
    assert selection["providers"] == []
    assert selection["provider_job_count"] == 0
    assert selection["run_quality"] is True
    assert selection["run_docs"] is False
    assert selection["run_compatibility"] is False


def test_select_providers_ci_plumbing_routes_to_runtime() -> None:
    """Verify CI workflow and selector script changes run the lightweight runtime provider instead of all providers."""
    manifest = load_manifest()
    selection = select_providers(
        manifest,
        [".github/workflows/ci.yaml", "scripts/ci/select_provider_tests.py"],
    )

    assert selection["mode"] == "selective"
    assert selection["providers"] == ["runtime"]
    assert selection["provider_job_count"] == 1
    assert selection["images"] == ["busybox:latest"]
    assert selection["run_quality"] is True
    assert selection["run_compatibility"] is True


def test_changed_files_for_range_uses_merge_base(tmp_path: Path) -> None:
    """Verify changed_files_for_range diffs against the merge-base when base advances ahead of branch."""
    assert GIT_EXECUTABLE is not None
    _init_git_repo(tmp_path)

    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "add", "base.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([GIT_EXECUTABLE, "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run([GIT_EXECUTABLE, "checkout", "-b", "feature"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "add", "feature.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([GIT_EXECUTABLE, "commit", "-m", "feature"], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run([GIT_EXECUTABLE, "checkout", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "upstream.txt").write_text("upstream\n", encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "add", "upstream.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([GIT_EXECUTABLE, "commit", "-m", "upstream"], cwd=tmp_path, check=True, capture_output=True)

    assert changed_files_for_range("main", "feature", cwd=tmp_path) == ["feature.txt"]


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
    assert sleeps == [5.0]

    with pytest.raises(UnknownProviderError, match="unknown provider"):
        pull_provider_images(manifest, "nonexistent", run_command=flaky_runner)


def test_build_commands_and_evaluate_required_jobs() -> None:
    """Verify pytest command construction and required-job status evaluation."""
    manifest = load_manifest()
    compat_cmd = build_compatibility_command(manifest)
    assert compat_cmd[1:3] == ["-m", "pytest"]
    assert "tests/test_valkey.py::test_plugin_imports_without_valkey" in compat_cmd

    compat_cov_cmd = build_compatibility_command(manifest, coverage=True)
    assert compat_cov_cmd[1:7] == ["-m", "coverage", "run", "--parallel-mode", "--source=pytest_databases", "-m"]

    provider_cmd = build_provider_command(manifest, "minio", coverage=True)
    assert "--source=pytest_databases" in provider_cmd
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


@pytest.mark.parametrize(
    ("use_live", "include_cost_budgets", "pass_manifest", "expected_load_calls"),
    [
        (True, True, False, 0),
        (False, True, False, 0),
        (False, False, True, 0),
        (False, False, False, 1),
    ],
    ids=[
        "live_manifest",
        "selection_cost_budgets",
        "explicit_manifest",
        "legacy_fallback",
    ],
)
def test_render_summary_dynamic_cost_budgets(
    monkeypatch: pytest.MonkeyPatch,
    use_live: bool,
    include_cost_budgets: bool,
    pass_manifest: bool,
    expected_load_calls: int,
) -> None:
    """Verify render_summary computes dynamic cost budgets without hidden disk reads.

    Args:
        monkeypatch: Pytest fixture for patching module attributes.
        use_live: Whether to run against the checked-in repository manifest.
        include_cost_budgets: Whether selection includes computed ``cost_budgets``.
        pass_manifest: Whether to pass ``manifest=`` explicitly to ``render_summary``.
        expected_load_calls: Expected count of fallback ``load_manifest`` calls.
    """
    if use_live:
        manifest = load_manifest()
        expected_budgets = {
            "shared_runtime_jobs": 30,
            "shared_runtime_pulls": 72,
            "full_jobs": 150,
            "full_pulls": 360,
        }
    else:
        manifest = _synthetic_budget_manifest()
        expected_budgets = {
            "shared_runtime_jobs": 2,
            "shared_runtime_pulls": 3,
            "full_jobs": 4,
            "full_pulls": 6,
        }

    load_calls = 0

    def _mock_load_manifest() -> dict[str, Any]:
        nonlocal load_calls
        load_calls += 1
        if expected_load_calls == 0:
            message = "load_manifest must not be called when budgets or manifest are supplied"
            raise AssertionError(message)
        return manifest

    monkeypatch.setattr(select_provider_tests, "load_manifest", _mock_load_manifest)

    if include_cost_budgets:
        selection = select_providers(manifest, ["README.md"])
        assert selection["cost_budgets"] == expected_budgets
    else:
        selection = _minimal_selection_without_budgets()

    summary = render_summary(selection, manifest=manifest) if pass_manifest else render_summary(selection)

    assert load_calls == expected_load_calls
    assert "| Docs-only target | 0 | 0 |" in summary
    assert "| Single-provider target | 1 | provider-owned only |" in summary
    assert (
        f"| Shared runtime target | {expected_budgets['shared_runtime_jobs']} | "
        f"{expected_budgets['shared_runtime_pulls']} |" in summary
    )
    assert (
        f"| Nightly/manual full target | {expected_budgets['full_jobs']} | "
        f"{expected_budgets['full_pulls']} |" in summary
    )
    assert "19" not in summary
    assert "53" not in summary
    assert "95" not in summary
    assert "265" not in summary
    assert "about 540" not in summary
    assert "Legacy eager PR baseline" not in summary


@pytest.mark.parametrize(
    "missing_key",
    [
        "shared_runtime_jobs",
        "shared_runtime_pulls",
        "full_jobs",
        "full_pulls",
    ],
)
def test_render_summary_rejects_malformed_cost_budgets_without_disk_read(
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    """Verify partial cost_budgets mappings fail with KeyError without calling load_manifest.

    Args:
        monkeypatch: Pytest fixture for patching module attributes.
        missing_key: Budget key omitted from the selection payload.
    """

    def _forbid_load_manifest() -> dict[str, Any]:
        message = "load_manifest must not be called when selection supplies cost_budgets"
        raise AssertionError(message)

    monkeypatch.setattr(select_provider_tests, "load_manifest", _forbid_load_manifest)

    budgets = {
        "shared_runtime_jobs": 2,
        "shared_runtime_pulls": 3,
        "full_jobs": 4,
        "full_pulls": 6,
    }
    budgets.pop(missing_key)
    selection = _minimal_selection_without_budgets()
    selection["cost_budgets"] = budgets

    with pytest.raises(KeyError, match=missing_key):
        render_summary(selection)


@pytest.mark.parametrize(
    ("base_overrides", "head_overrides", "base_ref", "expected"),
    [
        ({}, {}, "main", []),
        (
            {},
            {"provider_updates": {"minio": {"images": ["cgr.dev/chainguard/minio:v2"]}}},
            "main",
            ["minio"],
        ),
        (
            {
                "removed_providers": ("minio",),
                "compatibility_paths": ["tests/test_postgres.py::test_plugin_imports_without_psycopg"],
            },
            {
                "provider_updates": {"postgres": {"images": ["postgres:17"]}},
                "compatibility_paths": ["tests/test_postgres.py::test_plugin_imports_without_psycopg"],
            },
            "main",
            ["minio", "postgres"],
        ),
        (
            {},
            {
                "provider_updates": {
                    "minio": {"images": ["cgr.dev/chainguard/minio:v2"]},
                    "rustfs": {"images": ["rustfs/rustfs:v2"]},
                }
            },
            "main",
            ["minio", "rustfs"],
        ),
        (
            {},
            {"shared_updates": {"metadata_only_globs": ["Makefile", "LICENSE"]}},
            "main",
            None,
        ),
        (
            {},
            {"shared_updates": {"supported_python_versions": ["3.12"]}},
            "main",
            None,
        ),
        (
            {},
            {"removed_providers": ("rustfs",)},
            "main",
            None,
        ),
        (
            {},
            {"compatibility_paths": ["tests/test_minio.py::test_plugin_imports_without_minio"]},
            "main",
            None,
        ),
        (
            {},
            {"compatibility_paths": [*_DEFAULT_COMPATIBILITY_PATHS, "tests/test_minio.py::test_new"]},
            "main",
            ["minio"],
        ),
        (
            {},
            {"compatibility_paths": [*_DEFAULT_COMPATIBILITY_PATHS, "tests/test_unowned.py::test_x"]},
            "main",
            None,
        ),
        (
            {
                "provider_updates": {
                    "minio": {"test_paths": ["tests/test_shared.py"]},
                    "rustfs": {"test_paths": ["tests/test_shared.py"]},
                }
            },
            {
                "provider_updates": {
                    "minio": {"test_paths": ["tests/test_shared.py"]},
                    "rustfs": {"test_paths": ["tests/test_shared.py"]},
                },
                "compatibility_paths": [*_DEFAULT_COMPATIBILITY_PATHS, "tests/test_shared.py::test_x"],
            },
            "main",
            None,
        ),
        ({}, {}, "missing-ref", None),
    ],
    ids=[
        "unchanged",
        "single_provider_edit",
        "multiple_providers_edited_and_added",
        "multiple_existing_providers_edited",
        "shared_metadata_globs_changed",
        "shared_python_versions_changed",
        "provider_removed",
        "compatibility_entry_removed",
        "compatibility_entry_added_single_owner",
        "compatibility_entry_added_unowned",
        "compatibility_entry_added_multi_owner",
        "missing_base_ref",
    ],
)
def test_changed_manifest_provider_ids_branches(
    tmp_path: Path,
    base_overrides: dict[str, Any],
    head_overrides: dict[str, Any],
    base_ref: str,
    expected: list[str] | None,
) -> None:
    """Verify changed_manifest_provider_ids classification across manifest diff branches.

    Args:
        tmp_path: Temporary directory for the isolated git repository.
        base_overrides: Overrides passed to ``_manifest_with`` for the committed base manifest.
        head_overrides: Overrides passed to ``_manifest_with`` for the candidate head manifest.
        base_ref: Git reference name queried against the temporary repository.
        expected: Expected sorted provider list or ``None`` when all-providers escalation is required.
    """
    base_manifest = _manifest_with(**base_overrides)
    head_manifest = _manifest_with(**head_overrides)
    _commit_base_manifest(tmp_path, base_manifest)
    assert changed_manifest_provider_ids(base_ref, head_manifest, cwd=tmp_path) == expected


def test_changed_manifest_provider_ids_missing_git_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify changed_manifest_provider_ids raises RuntimeError when git is unavailable.

    Args:
        monkeypatch: Pytest fixture for patching module attributes.
        tmp_path: Temporary directory passed as repository root.
    """
    monkeypatch.setattr(select_provider_tests, "GIT_EXECUTABLE", None)
    with pytest.raises(RuntimeError, match="git executable was not found"):
        changed_manifest_provider_ids("main", _manifest_with(), cwd=tmp_path)


def _synthetic_budget_manifest() -> dict[str, Any]:
    """Return a two-provider, two-Python manifest for deterministic budget testing."""
    return {
        "schema_version": 1,
        "supported_python_versions": ["3.12", "3.13"],
        "shared_all_provider_paths": [],
        "provider_scoped_dependency_paths": ["pyproject.toml"],
        "docs_only_globs": ["*.md"],
        "metadata_only_globs": ["Makefile"],
        "compatibility_test_paths": [],
        "providers": {
            "alpha": {
                "source_globs": ["src/alpha.py"],
                "test_paths": ["tests/test_alpha.py"],
                "images": ["alpha:1"],
                "docs_globs": ["docs/alpha.rst"],
            },
            "beta": {
                "source_globs": ["src/beta.py"],
                "test_paths": ["tests/test_beta.py"],
                "images": ["beta:1", "beta:2"],
                "docs_globs": ["docs/beta.rst"],
            },
        },
    }


def _minimal_selection_without_budgets() -> dict[str, Any]:
    """Return a synthetic selection payload omitting ``cost_budgets``."""
    return {
        "mode": "selective",
        "providers": ["alpha"],
        "provider_job_count": 1,
        "image_pull_count": 1,
        "reason": "selected providers owning changed paths: alpha",
        "changed_paths": ["src/alpha.py"],
        "test_paths": ["tests/test_alpha.py"],
        "images": ["alpha:1"],
        "provider_images": {"alpha": ["alpha:1"]},
    }


def _manifest_with(
    *,
    shared_updates: Mapping[str, Any] | None = None,
    provider_updates: Mapping[str, Mapping[str, Any]] | None = None,
    removed_providers: tuple[str, ...] = (),
    compatibility_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a synthetic provider manifest with targeted overrides.

    Args:
        shared_updates: Top-level manifest key overrides.
        provider_updates: Per-provider field overrides merged into ``providers``.
        removed_providers: Provider IDs to remove from ``providers``.
        compatibility_paths: Replacement list for ``compatibility_test_paths``.

    Returns:
        Copy of the base synthetic manifest with requested overrides applied.
    """
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "supported_python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "shared_all_provider_paths": ["src/pytest_databases/_service.py"],
        "provider_scoped_dependency_paths": ["pyproject.toml", "uv.lock"],
        "docs_only_globs": ["*.md", "docs/**"],
        "metadata_only_globs": ["Makefile"],
        "compatibility_test_paths": list(_DEFAULT_COMPATIBILITY_PATHS),
        "providers": {
            "minio": {
                "source_globs": ["src/pytest_databases/docker/minio.py"],
                "test_paths": ["tests/test_minio.py"],
                "images": ["cgr.dev/chainguard/minio:latest"],
                "docs_globs": ["docs/supported-databases/minio.rst"],
            },
            "postgres": {
                "source_globs": ["src/pytest_databases/docker/postgres.py"],
                "test_paths": ["tests/test_postgres.py"],
                "images": ["postgres:18"],
                "docs_globs": ["docs/supported-databases/postgres.rst"],
            },
            "rustfs": {
                "source_globs": ["src/pytest_databases/docker/rustfs.py"],
                "test_paths": ["tests/test_rustfs.py"],
                "images": ["rustfs/rustfs:latest"],
                "docs_globs": ["docs/supported-databases/rustfs.rst"],
            },
        },
    }
    if shared_updates:
        manifest.update(copy.deepcopy(dict(shared_updates)))
    if compatibility_paths is not None:
        manifest["compatibility_test_paths"] = list(compatibility_paths)
    if provider_updates:
        for provider_id, updates in provider_updates.items():
            manifest["providers"][provider_id].update(copy.deepcopy(dict(updates)))
    for provider_id in removed_providers:
        manifest["providers"].pop(provider_id, None)
    return manifest


def _init_git_repo(repo_path: Path) -> None:
    """Initialize a temporary git repository with unsigned test commits enabled.

    Args:
        repo_path: Root path of the temporary git repository.
    """
    assert GIT_EXECUTABLE is not None
    subprocess.run([GIT_EXECUTABLE, "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run([GIT_EXECUTABLE, "config", "user.name", "Test"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        [GIT_EXECUTABLE, "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [GIT_EXECUTABLE, "config", "commit.gpgsign", "false"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _commit_base_manifest(repo_path: Path, manifest: Mapping[str, Any]) -> None:
    """Create a temporary git repository containing a committed base manifest.

    Args:
        repo_path: Root path of the temporary git repository.
        manifest: Manifest dictionary to write and commit on ``main``.
    """
    assert GIT_EXECUTABLE is not None
    _init_git_repo(repo_path)
    manifest_path = repo_path / MANIFEST_REPOSITORY_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "add", MANIFEST_REPOSITORY_PATH], cwd=repo_path, check=True, capture_output=True)
    subprocess.run([GIT_EXECUTABLE, "commit", "-m", "base manifest"], cwd=repo_path, check=True, capture_output=True)
