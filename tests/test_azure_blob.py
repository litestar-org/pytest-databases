from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


AZURE_BLOB_TEST_HELPERS = """
import json


def run_az(docker_service, service, *args):
    return docker_service._client.containers.run(
        "mcr.microsoft.com/azure-cli:latest",
        ["az", "storage", *args, "--connection-string", service.connection_string],
        network_mode="host",
        remove=True,
    )


def az_container_exists(docker_service, service, container_name):
    raw = run_az(docker_service, service, "container", "exists", "--name", container_name)
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)["exists"]
"""


def test_plugin_imports_without_azure_storage_blob(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "azure.storage.blob" or name.startswith("azure.storage.blob."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.azure_blob  # noqa: F401
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases._service import DockerService
from pytest_databases.docker.azure_blob import AzureBlobService

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]

{AZURE_BLOB_TEST_HELPERS}


def test_one(
    docker_service: DockerService,
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert az_container_exists(docker_service, azure_blob_service, azure_blob_default_container_name)


def test_two(
    docker_service: DockerService,
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert az_container_exists(docker_service, azure_blob_service, azure_blob_default_container_name)
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
import pytest
from pytest_databases._service import DockerService
from pytest_databases.docker.azure_blob import AzureBlobService

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


@pytest.fixture(scope="session")
def azure_blob_xdist_isolation_level():
    return "server"


{AZURE_BLOB_TEST_HELPERS}


def test_one(
    docker_service: DockerService,
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert az_container_exists(docker_service, azure_blob_service, azure_blob_default_container_name)


def test_two(
    docker_service: DockerService,
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert az_container_exists(docker_service, azure_blob_service, azure_blob_default_container_name)
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases._service import DockerService
from pytest_databases.docker.azure_blob import AzureBlobService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


{AZURE_BLOB_TEST_HELPERS}


def test_one(
    docker_service: DockerService,
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert az_container_exists(docker_service, azure_blob_service, azure_blob_default_container_name)
    assert azure_blob_service.account_name == f"test_account_{{get_xdist_worker_num()}}"


def test_two(
    docker_service: DockerService,
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert az_container_exists(docker_service, azure_blob_service, azure_blob_default_container_name)
    assert azure_blob_service.account_name == f"test_account_{{get_xdist_worker_num()}}"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
