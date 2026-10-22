RustFS
======

Integration with `RustFS <https://rustfs.com>`_, a high-performance, S3-compatible object storage service written in Rust.

This integration provides a container-managed RustFS service for testing S3-compatible storage without requiring any additional Python dependencies in the core package.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install your own S3 client library (for example ``boto3`` or ``minio``) to interact with the service in your tests.

Docker Image
------------

* `Official RustFS Docker Image <https://hub.docker.com/r/rustfs/rustfs>`_ (override via ``rustfs_image``)

.. note::

   Current ``rustfs/rustfs:latest`` images refuse to start when the root
   credentials look like documented defaults (e.g. ``rustfsadmin`` /
   ``rustfsadmin``). The shipped defaults use non-default-looking values
   so the fixture starts cleanly out of the box.

Usage Example
-------------

Using ``minio``:

.. code-block:: python

    from minio import Minio
    from pytest_databases.docker.rustfs import RustfsService

    pytest_plugins = ["pytest_databases.docker.rustfs"]

    def test_rustfs_with_minio(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
        client = Minio(
            endpoint=rustfs_service.endpoint,
            access_key=rustfs_service.access_key,
            secret_key=rustfs_service.secret_key,
            secure=rustfs_service.secure,
        )
        assert client.bucket_exists(rustfs_default_bucket_name)

Using ``boto3``:

.. code-block:: python

    import boto3
    from pytest_databases.docker.rustfs import RustfsService

    pytest_plugins = ["pytest_databases.docker.rustfs"]

    def test_rustfs_with_boto3(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
        s3 = boto3.client(
            "s3",
            endpoint_url=rustfs_service.endpoint_url,
            aws_access_key_id=rustfs_service.access_key,
            aws_secret_access_key=rustfs_service.secret_key,
            region_name="us-east-1",
        )

        response = s3.list_buckets()
        bucket_names = [b["Name"] for b in response["Buckets"]]
        assert rustfs_default_bucket_name in bucket_names

Available Fixtures
------------------

* ``rustfs_image``: Container image for the RustFS server (default: ``rustfs/rustfs:latest``).
* ``rustfs_access_key``: Access key for RustFS (default: ``pytest-databases-rustfs``).
* ``rustfs_secret_key``: Secret key for RustFS (default: ``pytest-databases-rustfs-secret``).
* ``rustfs_secure``: Whether to use HTTPS for RustFS (default: ``False``).
* ``rustfs_default_bucket_name``: Default bucket automatically provisioned on startup (default: ``pytest-databases``).
* ``rustfs_service``: Provides a running ``RustfsService`` instance.

Service API
-----------

.. automodule:: pytest_databases.docker.rustfs
   :members:
   :undoc-members:
   :show-inheritance:
