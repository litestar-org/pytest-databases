Azure Blob Storage
==================

Integration with `Azure Blob Storage <https://azure.microsoft.com/en-us/products/storage/blobs>`_ using the `Azurite <https://github.com/Azure/Azurite>`_ emulator image.

Installation
------------

The Azure Blob Storage service fixture initializes the default container using Python stdlib HTTP requests signed with ``SharedKey`` HMAC-SHA256 authentication, so no Azure SDK dependency or CLI sidecar container is required to start the service:

.. code-block:: bash

   pip install pytest-databases

Usage Example
-------------

.. code-block:: python

    from azure.storage.blob import ContainerClient
    from pytest_databases.docker.azure_blob import AzureBlobService

    pytest_plugins = ["pytest_databases.docker.azure_blob"]


    def test_azure_blob(
        azure_blob_service: AzureBlobService,
        azure_blob_default_container_name: str,
    ) -> None:
        with ContainerClient.from_connection_string(
            azure_blob_service.connection_string,
            container_name=azure_blob_default_container_name,
        ) as container_client:
            assert container_client.exists()

Available Fixtures
------------------

* ``azurite_in_memory``: Whether to use in-memory storage for Azurite (default: ``True``).
* ``azure_blob_xdist_isolation_level``: Isolation mode under ``pytest-xdist`` (``"database"`` per-worker account or ``"server"`` per-worker container).
* ``azure_blob_service``: A fixture that provides an :class:`~pytest_databases.docker.azure_blob.AzureBlobService` instance.
* ``azure_blob_default_container_name``: The default container name created on startup (default: ``"pytest-databases"``).
* ``azure_blob_container_client``: Deprecated fixture that provides a synchronous ``ContainerClient``.
* ``azure_blob_default_container``: Deprecated alias for ``azure_blob_container_client``.
* ``azure_blob_async_container_client``: Deprecated fixture that provides an asynchronous ``ContainerClient``.

Service API
-----------

.. automodule:: pytest_databases.docker.azure_blob
   :members:
   :undoc-members:
   :show-inheritance:
