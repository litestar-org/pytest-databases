RustFS
======

Integration with `RustFS <https://rustfs.com>`_, a high-performance S3-compatible object storage system built in Rust.

RustFS is 2.3x faster than MinIO for small object payloads and is released under the permissive Apache 2.0 license. It provides full S3 compatibility and supports AWS Signature v2 and v4 authentication.

This integration uses `boto3 <https://boto3.amazonaws.com/v1/documentation/api/latest/index.html>`_ (AWS SDK for Python) to interact with RustFS, which provides S3-compatible object storage for testing and development.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[rustfs]

Docker Image
------------

`Official RustFS Docker Image <https://hub.docker.com/r/rustfs/rustfs>`_

Configuration
-------------

* ``RUSTFS_ACCESS_KEY``: Access key for RustFS (default: "rustfsadmin")
* ``RUSTFS_SECRET_KEY``: Secret key for RustFS (default: "rustfsadmin")
* ``RUSTFS_SECURE``: Whether to use HTTPS (default: "false")

Usage Example
-------------

.. code-block:: python

    import pytest
    from pytest_databases.docker.rustfs import RustfsService

    pytest_plugins = ["pytest_databases.docker.rustfs"]

    def test_with_service(rustfs_service: RustfsService) -> None:
        import boto3
        client = boto3.client(
            "s3",
            endpoint_url=f"http://{rustfs_service.endpoint}",
            aws_access_key_id=rustfs_service.access_key,
            aws_secret_access_key=rustfs_service.secret_key,
        )
        client.create_bucket(Bucket="test-bucket")
        response = client.list_buckets()
        assert any(b["Name"] == "test-bucket" for b in response["Buckets"])

    def test_with_client(rustfs_client) -> None:
        rustfs_client.create_bucket(Bucket="test-bucket")
        response = rustfs_client.list_buckets()
        assert any(b["Name"] == "test-bucket" for b in response["Buckets"])

Available Fixtures
------------------

* ``rustfs_access_key``: The access key for RustFS defaults to os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin").
* ``rustfs_secret_key``: The secret key for RustFS defaults to os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin").
* ``rustfs_secure``: Whether to use HTTPS for RustFS defaults to os.getenv("RUSTFS_SECURE", "false").
* ``rustfs_service``: A fixture that provides a RustFS service.
* ``rustfs_client``: A fixture that provides a boto3 S3 client configured for RustFS.
* ``rustfs_default_bucket_name``: A fixture that provides the default bucket name.
* ``xdist_rustfs_isolation_level``: A fixture that controls xdist isolation strategy ("database" or "server").

Service API
-----------

.. automodule:: pytest_databases.docker.rustfs
   :members:
   :undoc-members:
   :show-inheritance:
