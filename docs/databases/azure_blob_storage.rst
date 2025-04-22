\
.. _db_azure_blob:

Azure Blob Storage
==================

Integration with Azure Blob Storage via Azurite Emulator.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[azure-blob]

Emulator
--------

`Azurite Docker Image <https://hub.docker.com/_/microsoft-azure-storage-azurite>`_

Configuration
-------------

* ``AZURE_BLOB_IMAGE``: Docker image to use for Azure Blob Storage (default: "mcr.microsoft.com/azure-storage/azurite:latest")
* ``XDIST_AZURE_BLOB_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``AZURE_BLOB_ACCOUNT_NAME``: Account name for Azure Blob Storage (default: "devstoreaccount1")
* ``AZURE_BLOB_ACCOUNT_KEY``: Account key for Azure Blob Storage (default: "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==")

API
---

.. automodule:: pytest_databases.docker.azure_blob
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
