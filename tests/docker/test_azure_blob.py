import pytest

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from azure.storage.blob import ContainerClient

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


def test_one(azure_blob_container_client: ContainerClient) -> None:
    azure_blob_container_client.create_container()


def test_two(azure_blob_container_client: ContainerClient) -> None:
    assert azure_blob_container_client.exists()
""")
    result = pytester.runpytest()
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
import pytest
from azure.storage.blob import ContainerClient

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


@pytest.fixture(scope="session")
def azure_blob_xdist_isolation_level():
    return "server"


def test_one(azure_blob_container_client: ContainerClient) -> None:
    assert not azure_blob_container_client.exists()
    azure_blob_container_client.create_container()


def test_two(azure_blob_container_client: ContainerClient) -> None:
    assert not azure_blob_container_client.exists()
    azure_blob_container_client.create_container()
""")
    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
from azure.storage.blob import ContainerClient
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


def test_one(azure_blob_container_client: ContainerClient, azure_blob_default_container_name: str) -> None:
    assert not azure_blob_container_client.exists()
    azure_blob_container_client.create_container()
    assert azure_blob_container_client.container_name == azure_blob_default_container_name
    assert azure_blob_container_client.account_name == f"test_account_{get_xdist_worker_num()}"


def test_two(azure_blob_container_client: ContainerClient, azure_blob_default_container_name: str) -> None:
    assert not azure_blob_container_client.exists()
    azure_blob_container_client.create_container()
    assert azure_blob_container_client.container_name == azure_blob_default_container_name
    assert azure_blob_container_client.account_name == f"test_account_{get_xdist_worker_num()}"

""")
    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)
