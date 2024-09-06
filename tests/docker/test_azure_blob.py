from azure.storage.blob import ContainerClient

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


def test_azure_blob_service(azure_blob_container_client: ContainerClient) -> None:
    assert not azure_blob_container_client.exists()
