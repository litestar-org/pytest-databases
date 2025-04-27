MinIO
=====

Integration with `MinIO <https://min.io>`_, an S3-compatible object storage service.

This integration uses the official `MinIO Python Client <https://min.io/docs/minio/linux/developers/python/minio-py.html>`_ to interact with MinIO, which provides S3-compatible object storage for testing and development.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[minio]

Docker Image
------------

`Official MinIO Docker Image <https://quay.io/minio/minio>`_

Configuration
-------------

* ``MINIO_ACCESS_KEY``: Access key for MinIO (default: "minio")
* ``MINIO_SECRET_KEY``: Secret key for MinIO (default: "minio123")
* ``MINIO_SECURE``: Whether to use HTTPS (default: "false")

Usage Example
-------------

.. code-block:: python

    import pytest
    from minio import Minio
    from pytest_databases.docker.minio import MinioService

    pytest_plugins = ["pytest_databases.docker.minio"]

    def test(minio_service: MinioService) -> None:
        client = Minio(
            endpoint=minio_service.endpoint,
            access_key=minio_service.access_key,
            secret_key=minio_service.secret_key,
            secure=minio_service.secure,
        )
        client.make_bucket("test-bucket")
        assert client.bucket_exists("test-bucket")

    def test(minio_client: Minio) -> None:
        minio_client.make_bucket("test-bucket")
        assert minio_client.bucket_exists("test-bucket")

Available Fixtures
------------------

* ``minio_access_key``: The access key for MinIO defaults to os.getenv("MINIO_ACCESS_KEY", "minio").
* ``minio_secret_key``: The secret key for MinIO defaults to os.getenv("MINIO_SECRET_KEY", "minio123").
* ``minio_secure``: Whether to use HTTPS for MinIO defaults to os.getenv("MINIO_SECURE", "false").
* ``minio_service``: A fixture that provides a MinIO service.
* ``minio_client``: A fixture that provides a MinIO client.
* ``minio_default_bucket_name``: A fixture that provides the default bucket name.

Service API
-----------

.. automodule:: pytest_databases.docker.minio
   :members:
   :undoc-members:
   :show-inheritance:
