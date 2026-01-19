import pytest


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from minio import Minio

pytest_plugins = [
    "pytest_databases.docker.minio",
]


def test_one(minio_client: Minio) -> None:
    minio_client.make_bucket("pytest-databases-test-no-xdist")
    assert minio_client.bucket_exists("pytest-databases-test-no-xdist")


def test_two(minio_client: Minio) -> None:
    assert minio_client.bucket_exists("pytest-databases-test-no-xdist")
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from minio import Minio
from pytest_databases.helpers import get_xdist_worker_num
pytest_plugins = [
    "pytest_databases.docker.minio",
]


@pytest.fixture(scope="session")
def xdist_minio_isolation_level():
    return "server"


def test_one(minio_client: Minio, minio_default_bucket_name: str) -> None:
    assert minio_client.bucket_exists(minio_default_bucket_name)
    isolated_bucket_name = f"{minio_default_bucket_name}-isolated-{get_xdist_worker_num()}"
    assert not minio_client.bucket_exists(isolated_bucket_name)
    minio_client.make_bucket(isolated_bucket_name)
    assert minio_client.bucket_exists(isolated_bucket_name)


def test_two(minio_client: Minio, minio_default_bucket_name: str) -> None:
    assert minio_client.bucket_exists(minio_default_bucket_name)
    isolated_bucket_name = f"{minio_default_bucket_name}-isolated-{get_xdist_worker_num()}"
    assert not minio_client.bucket_exists(isolated_bucket_name)
    minio_client.make_bucket(isolated_bucket_name)
    assert minio_client.bucket_exists(isolated_bucket_name)
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
from minio import Minio
from pytest_databases.helpers import get_xdist_worker_num
pytest_plugins = [
    "pytest_databases.docker.minio",
]


def test_one(minio_client: Minio, minio_default_bucket_name: str) -> None:
    assert minio_client.bucket_exists(minio_default_bucket_name)
    isolated_bucket_name = f"{minio_default_bucket_name}-isolated-{get_xdist_worker_num()}"
    assert not minio_client.bucket_exists(isolated_bucket_name)
    minio_client.make_bucket(isolated_bucket_name)
    assert minio_client.bucket_exists(isolated_bucket_name)

def test_two(minio_client: Minio, minio_default_bucket_name: str) -> None:
    assert minio_client.bucket_exists(minio_default_bucket_name)
    isolated_bucket_name = f"{minio_default_bucket_name}-isolated-{get_xdist_worker_num()}"
    assert not minio_client.bucket_exists(isolated_bucket_name)
    minio_client.make_bucket(isolated_bucket_name)
    assert minio_client.bucket_exists(isolated_bucket_name)

""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
