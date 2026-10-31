MinIO
=====

Integration with `MinIO <https://min.io>`_, an S3-compatible object storage service.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install your preferred S3 or MinIO client library (for example ``minio`` or ``boto3``) alongside ``pytest-databases``.

Docker Images
-------------

* Server: ``cgr.dev/chainguard/minio:latest`` (override via ``minio_image``)
* Client: ``cgr.dev/chainguard/minio-client:latest`` (override via ``minio_client_image``)

Usage Example
-------------

.. code-block:: python

    from minio import Minio
    from pytest_databases.docker.minio import MinioService

    pytest_plugins = ["pytest_databases.docker.minio"]

    def test_minio_service(minio_service: MinioService, minio_default_bucket_name: str) -> None:
        client = Minio(
            endpoint=minio_service.endpoint,
            access_key=minio_service.access_key,
            secret_key=minio_service.secret_key,
            secure=minio_service.secure,
        )
        assert client.bucket_exists(minio_default_bucket_name)

Available Fixtures
------------------

* ``minio_image``: Container image for the MinIO server (default: ``cgr.dev/chainguard/minio:latest``).
* ``minio_client_image``: Container image for the MinIO ``mc`` client (default: ``cgr.dev/chainguard/minio-client:latest``).
* ``minio_access_key``: Access key for MinIO (default: ``minio``; override via ``MINIO_ACCESS_KEY``).
* ``minio_secret_key``: Secret key for MinIO (default: ``minio123``; override via ``MINIO_SECRET_KEY``).
* ``minio_secure``: Whether to use HTTPS for MinIO (default: ``False``; override via ``MINIO_SECURE``).
* ``minio_default_bucket_name``: Default bucket automatically provisioned on startup (default: ``pytest-databases``).
* ``minio_service``: Provides a running ``MinioService`` instance.

Service API
-----------

.. automodule:: pytest_databases.docker.minio
   :members:
   :undoc-members:
   :show-inheritance:
