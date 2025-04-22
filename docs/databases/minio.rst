\
.. _db_minio:

MinIO
=====

Integration with MinIO.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[minio]

Docker Image
------------

`Official MinIO Docker Image <https://hub.docker.com/r/minio/minio>`_

Configuration
-------------

* ``MINIO_IMAGE``: Docker image to use for MinIO (default: "quay.io/minio/minio:latest")
* ``XDIST_MINIO_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``MINIO_ACCESS_KEY``: Access key for MinIO (default: "minioadmin")
* ``MINIO_SECRET_KEY``: Secret key for MinIO (default: "minioadmin")
* ``MINIO_SECURE``: Whether to use HTTPS for MinIO (default: "False")

API
---

.. automodule:: pytest_databases.docker.minio
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
