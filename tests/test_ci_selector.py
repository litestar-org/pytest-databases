from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from scripts.ci.select_provider_tests import (
    ManifestValidationError,
    changed_files_for_range,
    parse_name_status,
    select_providers,
    validate_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

PROJECT_ROOT = Path(__file__).parents[1]
MANIFEST_PATH = PROJECT_ROOT / ".github" / "ci" / "provider-groups.json"

EXPECTED_PROVIDERS = {
    "azure_blob",
    "bigquery",
    "cockroachdb",
    "dolt",
    "elasticsearch",
    "gizmosql",
    "mariadb",
    "minio",
    "mongodb",
    "mssql",
    "mysql",
    "oracle",
    "postgres",
    "redis",
    "runtime",
    "rustfs",
    "spanner",
    "valkey",
    "yugabyte",
}


def test_provider_manifest_inventory() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    assert manifest["schema_version"] == 1
    assert set(manifest["providers"]) == EXPECTED_PROVIDERS
    for provider_id, provider in manifest["providers"].items():
        assert provider["source_globs"], provider_id
        assert provider["test_paths"], provider_id
        assert provider["images"], provider_id
        assert provider["docs_globs"], provider_id


def test_provider_manifest_owns_every_adapter_source_and_test_once() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    providers = manifest["providers"]
    owned_sources = [path for provider in providers.values() for path in provider["source_globs"]]
    owned_tests = [path for provider in providers.values() for path in provider["test_paths"]]
    adapter_sources = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src" / "pytest_databases" / "docker").glob("*.py")
        if path.name != "__init__.py"
    }
    adapter_sources.add("src/pytest_databases/_service.py")
    provider_tests = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "tests").glob("test_*.py")
        if not path.name.startswith("test_ci_")
    }

    assert len(owned_sources) == len(set(owned_sources))
    assert len(owned_tests) == len(set(owned_tests))
    assert set(owned_sources) == adapter_sources
    assert set(owned_tests) == provider_tests


@pytest.fixture
def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())


@pytest.mark.parametrize(
    ("changed_paths", "expected_mode", "expected_providers"),
    [
        (["src/pytest_databases/docker/postgres.py"], "selective", {"postgres"}),
        (["tests/test_gizmosql.py"], "selective", {"gizmosql"}),
        (["docs/supported-databases/postgres.rst"], "docs-only", set()),
        (["README.md", "docs/usage.rst"], "docs-only", set()),
        (["src/pytest_databases/_service.py"], "all-providers", EXPECTED_PROVIDERS),
        (["pyproject.toml"], "all-providers", EXPECTED_PROVIDERS),
        (["src/pytest_databases/new_adapter.py"], "fail-closed", EXPECTED_PROVIDERS),
        (["tests/test_new_adapter.py"], "fail-closed", EXPECTED_PROVIDERS),
        ([], "fail-closed", EXPECTED_PROVIDERS),
    ],
)
def test_select_providers(
    manifest: dict[str, Any], changed_paths: list[str], expected_mode: str, expected_providers: set[str]
) -> None:
    result = select_providers(manifest, changed_paths)

    assert result["mode"] == expected_mode
    assert set(result["providers"]) == expected_providers
    assert result["changed_paths"] == changed_paths


def test_select_providers_deduplicates_paths_and_images(manifest: dict[str, Any]) -> None:
    result = select_providers(
        manifest,
        ["tests/test_redis.py", "tests/test_redis.py", "src/pytest_databases/docker/valkey.py"],
    )

    assert result["providers"] == ["redis", "valkey"]
    assert result["changed_paths"] == ["tests/test_redis.py", "src/pytest_databases/docker/valkey.py"]
    assert len(result["images"]) == len(set(result["images"]))


def test_select_providers_full_mode(manifest: dict[str, Any]) -> None:
    result = select_providers(manifest, ["README.md"], full=True, full_reason="ci:full label")

    assert result["mode"] == "full"
    assert set(result["providers"]) == EXPECTED_PROVIDERS
    assert result["reason"] == "ci:full label"
    assert len(result["provider_matrix"]["include"]) == len(EXPECTED_PROVIDERS) * 6
    assert result["provider_job_count"] == 114
    assert result["image_pull_count"] == 318
    assert {cell["python-version"] for cell in result["provider_matrix"]["include"]} == {
        "3.9",
        "3.10",
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    }


def test_selective_provider_matrix_uses_python_312(manifest: dict[str, Any]) -> None:
    result = select_providers(manifest, ["tests/test_bigquery.py"])

    assert result["provider_matrix"]["include"] == [
        {
            "provider": "bigquery",
            "python-version": "3.12",
            "test_paths": ["tests/test_bigquery.py"],
        }
    ]
    assert result["provider_job_count"] == 1
    assert result["image_pull_count"] == 1


def test_docs_only_selection_skips_code_jobs_and_requests_docs(manifest: dict[str, Any]) -> None:
    result = select_providers(manifest, ["CONTRIBUTING.rst"])

    assert result["run_docs"] is True
    assert result["run_quality"] is False
    assert result["run_compatibility"] is False
    assert result["provider_job_count"] == 0
    assert result["image_pull_count"] == 0


def test_parse_name_status_retains_deleted_and_both_renamed_paths() -> None:
    output = (
        b"D\0tests/test_old.py\0R100\0src/pytest_databases/docker/old.py\0src/pytest_databases/docker/postgres.py\0"
    )

    assert parse_name_status(output) == [
        "tests/test_old.py",
        "src/pytest_databases/docker/old.py",
        "src/pytest_databases/docker/postgres.py",
    ]


def test_changed_files_for_range_uses_the_requested_git_base(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run([git, "config", "user.email", "ci@example.com"], cwd=tmp_path, check=True)
    subprocess.run([git, "config", "user.name", "CI Test"], cwd=tmp_path, check=True)
    old_path = tmp_path / "tests" / "test_old.py"
    old_path.parent.mkdir()
    old_path.write_text("old\n")
    subprocess.run([git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([git, "commit", "--quiet", "-m", "base"], cwd=tmp_path, check=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    new_path = old_path.with_name("test_postgres.py")
    old_path.rename(new_path)
    subprocess.run([git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([git, "commit", "--quiet", "-m", "rename"], cwd=tmp_path, check=True)

    assert changed_files_for_range(base, "HEAD", cwd=tmp_path) == [
        "tests/test_old.py",
        "tests/test_postgres.py",
    ]


def test_validate_manifest_accepts_current_inventory(manifest: dict[str, Any]) -> None:
    validate_manifest(manifest, project_root=PROJECT_ROOT)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version=2), "schema_version"),
        (lambda value: value["providers"].pop("postgres"), "unowned provider source"),
        (
            lambda value: value["providers"]["valkey"]["test_paths"].append("tests/test_redis.py"),
            "duplicate test ownership",
        ),
        (lambda value: value["providers"]["postgres"].update(images=[]), "must own at least one image"),
        (
            lambda value: value["providers"]["postgres"]["test_paths"].append("../outside.py"),
            "unsafe path",
        ),
        (lambda value: value["providers"].update({"INVALID-ID": value["providers"].pop("dolt")}), "provider ID"),
    ],
)
def test_validate_manifest_rejects_drift(
    manifest: dict[str, Any], mutation: Callable[[dict[str, Any]], None], message: str
) -> None:
    invalid_manifest = deepcopy(manifest)
    mutation(invalid_manifest)

    with pytest.raises(ManifestValidationError, match=message):
        validate_manifest(invalid_manifest, project_root=PROJECT_ROOT)
