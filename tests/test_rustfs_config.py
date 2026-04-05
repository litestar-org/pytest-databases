import pytest

def test_rustfs_custom_bucket_env(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    pytester.makepyfile("""
import pytest
import os
from pytest_databases.docker.rustfs import RustfsService

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

def test_rustfs_env_bucket_name(rustfs_default_bucket_name: str) -> None:
    assert rustfs_default_bucket_name == "custom-env-bucket"
""")
    # Set the environment variable for the subprocess
    monkeypatch.setenv("RUSTFS_DEFAULT_BUCKET_NAME", "custom-env-bucket")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_rustfs_custom_bucket_fixture_override(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from pytest_databases.docker.rustfs import RustfsService

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

@pytest.fixture(scope="session")
def rustfs_default_bucket_name():
    return "fixture-override-bucket"

def test_rustfs_fixture_bucket_name(rustfs_default_bucket_name: str) -> None:
    assert rustfs_default_bucket_name == "fixture-override-bucket"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)
