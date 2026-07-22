from __future__ import annotations

import json
from pathlib import Path

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
        if path.name != "test_ci_selector.py"
    }

    assert len(owned_sources) == len(set(owned_sources))
    assert len(owned_tests) == len(set(owned_tests))
    assert set(owned_sources) == adapter_sources
    assert set(owned_tests) == provider_tests
