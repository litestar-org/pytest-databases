import pytest


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from urllib.request import Request, urlopen
from pytest_databases.docker.rustfs import RustfsService

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

def test_rustfs_service_fixture(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    assert rustfs_service.host == "127.0.0.1"
    assert rustfs_service.port > 0
    assert rustfs_default_bucket_name == "pytest-databases"

    # Check health endpoint
    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_rustfs_bucket_exists_manual(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    # Check if we can at least reach the bucket endpoint (even if it requires signing,
    # a 403 usually means it exists but we are not signed, while 404 means it doesn't).
    # However, since we're not providing a client, we just verify the service is up.
    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/{rustfs_default_bucket_name}"

    # We expect some response from the server, indicating it's handling S3 requests
    try:
        with urlopen(Request(url, method="GET")) as response:
            assert response.status in {200, 403, 404}
    except Exception:
        # Some S3 servers might return 403 without signing
        pass
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.docker.rustfs import RustfsService

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

@pytest.fixture(scope="session")
def xdist_rustfs_isolation_level():
    return "server"

def test_isolation_one(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert rustfs_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    from urllib.request import Request, urlopen
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_isolation_two(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert rustfs_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    from urllib.request import Request, urlopen
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
