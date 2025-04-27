Azure Blob Storage
==================

Integration with `Azure Blob Storage <https://azure.microsoft.com/en-us/products/storage/blobs>`_, a cloud-based object storage service.

This integration uses the official `Azure Storage Blobs Python Client <https://learn.microsoft.com/en-us/python/api/overview/azure/storage-blob-readme>`_ to interact with Azure Blob Storage, which provides scalable object storage for testing and development.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[azure]

Configuration
-------------

* ``AZURE_STORAGE_CONNECTION_STRING``: Connection string for Azure Blob Storage
* ``AZURE_STORAGE_ACCOUNT_NAME``: Account name for Azure Blob Storage
* ``AZURE_STORAGE_ACCOUNT_KEY``: Account key for Azure Blob Storage
* ``AZURE_STORAGE_CONTAINER_NAME``: Container name for Azure Blob Storage (default: "pytest-databases")

Usage Example
-------------

.. code-block:: python

    import pytest
    from azure.storage.blob import BlobServiceClient
    from pytest_databases.docker.azure_blob import AzureBlobStorageService
    pytest_plugins = ["pytest_databases.docker.azure_blob"]

    def test(azure_blob_storage_service: AzureBlobStorageService) -> None:
        client = BlobServiceClient.from_connection_string(
            azure_blob_storage_service.connection_string
        )
        container = client.get_container_client(azure_blob_storage_service.container_name)
        container.create_container()
        assert container.exists()

    def test(azure_blob_storage_client: BlobServiceClient) -> None:
        container = azure_blob_storage_client.get_container_client("test-container")
        container.create_container()
        assert container.exists()

Available Fixtures
------------------

* ``azurite_in_memory``: Whether to use in-memory storage for Azurite (default: ``True``)
* ``azure_blob_service``: A fixture that provides an Azure Blob Storage service.
* ``azure_blob_default_container_name``: The default container name for Azure Blob Storage (default: ``pytest-databases``)
* ``azure_blob_container_client``: A fixture that provides an Azure Blob Storage container client.
* ``azure_blob_async_container_client``: A fixture that provides an Azure Blob Storage container client for async operations.

Service API
-----------

.. automodule:: pytest_databases.docker.azure_blob
   :members:
   :undoc-members:
   :show-inheritance:
