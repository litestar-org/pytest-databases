import pytest

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    """Test RustFS fixtures work without xdist parallel execution."""
    pytester.makepyfile("""
import pytest
from typing import Any

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]


def test_one(rustfs_client: Any) -> None:
    # Create a test bucket
    rustfs_client.create_bucket(Bucket="pytest-databases-test-no-xdist")
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert "pytest-databases-test-no-xdist" in bucket_names


def test_two(rustfs_client: Any) -> None:
    # Verify bucket persists across tests (session-scoped)
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert "pytest-databases-test-no-xdist" in bucket_names
""")
    result = pytester.runpytest()
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Test RustFS with 'server' isolation - separate containers per worker."""
    pytester.makepyfile("""
import pytest
from typing import Any
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]


@pytest.fixture(scope="session")
def xdist_rustfs_isolation_level():
    return "server"


def test_one(rustfs_client: Any, rustfs_default_bucket_name: str) -> None:
    # Default bucket should exist
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert rustfs_default_bucket_name in bucket_names

    # Create an isolated bucket for this worker
    worker_num = get_xdist_worker_num()
    isolated_bucket_name = f"{rustfs_default_bucket_name}-isolated-{worker_num}"
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name not in bucket_names

    rustfs_client.create_bucket(Bucket=isolated_bucket_name)
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name in bucket_names


def test_two(rustfs_client: Any, rustfs_default_bucket_name: str) -> None:
    # Default bucket should exist
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert rustfs_default_bucket_name in bucket_names

    # Create an isolated bucket for this worker
    worker_num = get_xdist_worker_num()
    isolated_bucket_name = f"{rustfs_default_bucket_name}-isolated-{worker_num}"
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name not in bucket_names

    rustfs_client.create_bucket(Bucket=isolated_bucket_name)
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name in bucket_names
""")
    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Test RustFS with 'database' isolation - shared container, workers create own buckets."""
    pytester.makepyfile("""
from typing import Any
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]


def test_one(rustfs_client: Any, rustfs_default_bucket_name: str) -> None:
    # Default bucket should exist and be shared
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert rustfs_default_bucket_name in bucket_names

    # Workers can create their own isolated buckets
    worker_num = get_xdist_worker_num()
    isolated_bucket_name = f"{rustfs_default_bucket_name}-isolated-{worker_num}"
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name not in bucket_names

    rustfs_client.create_bucket(Bucket=isolated_bucket_name)
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name in bucket_names


def test_two(rustfs_client: Any, rustfs_default_bucket_name: str) -> None:
    # Default bucket should exist and be shared
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert rustfs_default_bucket_name in bucket_names

    # Workers can create their own isolated buckets
    worker_num = get_xdist_worker_num()
    isolated_bucket_name = f"{rustfs_default_bucket_name}-isolated-{worker_num}"
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name not in bucket_names

    rustfs_client.create_bucket(Bucket=isolated_bucket_name)
    response = rustfs_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]
    assert isolated_bucket_name in bucket_names
""")
    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)
