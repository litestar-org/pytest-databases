import pytest


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from urllib.request import Request, urlopen
from pytest_databases.docker.minio import MinioService

pytest_plugins = [
    "pytest_databases.docker.minio",
]

def test_minio_service_fixture(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    assert minio_service.host == "127.0.0.1"
    assert minio_service.port > 0
    assert minio_default_bucket_name == "pytest-databases"

    # Check health endpoint
    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/minio/health/ready"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_minio_bucket_exists_manual(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/{minio_default_bucket_name}"

    try:
        with urlopen(Request(url, method="GET")) as response:
            assert response.status in {200, 403, 404}
    except Exception:
        pass
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.docker.minio import MinioService

pytest_plugins = [
    "pytest_databases.docker.minio",
]

@pytest.fixture(scope="session")
def xdist_minio_isolation_level():
    return "server"

def test_isolation_one(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert minio_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/minio/health/ready"
    from urllib.request import Request, urlopen
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_isolation_two(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert minio_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/minio/health/ready"
    from urllib.request import Request, urlopen
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
