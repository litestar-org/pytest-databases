Azure Blob Storage
==================

Integration with `Azure Blob Storage <https://azure.microsoft.com/en-us/products/storage/blobs>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[azure-storage]

Usage Example
-------------

.. code-block:: python

    import pytest
    from azure.storage.blob import ContainerClient
    from pytest_databases.docker.azure_blob import AzureBlobService

    pytest_plugins = ["pytest_databases.docker.azure_blob"]

    def test(
        azure_blob_service: AzureBlobService,
        azure_blob_default_container_name: str,
    ) -> None:
        with ContainerClient.from_connection_string(
            azure_blob_service.connection_string,
            container_name=azure_blob_default_container_name,
        ) as container:
            container.create_container()
            assert container.exists()

Available Fixtures
------------------

* ``azurite_in_memory``: Whether to use in-memory storage for Azurite (default: ``True``).
* ``azure_blob_service``: A fixture that provides an Azure Blob Storage service.
* ``azure_blob_default_container_name``: The default container name for Azure Blob Storage (default: ``pytest-databases``).
* ``azure_blob_xdist_isolation_level``: Xdist isolation level for the service (default: ``database``).

Service API
-----------

.. automodule:: pytest_databases.docker.azure_blob
   :members:
   :undoc-members:
   :show-inheritance:
