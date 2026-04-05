RustFS
======

Integration with `RustFS <https://rustfs.com>`_, a high-performance, S3-compatible object storage service written in Rust.

This integration provides a Docker-managed RustFS service for testing S3-compatible storage without requiring any additional Python dependencies in the core package.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

*Note: You will need to install your own S3 client library (e.g., ``boto3`` or ``minio``) to interact with the service in your tests.*

Docker Image
------------

`Official RustFS Docker Image <https://hub.docker.com/r/rustfs/rustfs>`_

Configuration
-------------

* ``RUSTFS_ACCESS_KEY``: Access key for RustFS (default: "rustfsadmin")
* ``RUSTFS_SECRET_KEY``: Secret key for RustFS (default: "rustfsadmin")
* ``RUSTFS_SECURE``: Whether to use HTTPS (default: "false")
* ``RUSTFS_DEFAULT_BUCKET_NAME``: The default bucket to create (default: "pytest-databases")

Usage Example
-------------

Using ``boto3``:

.. code-block:: python

    import boto3
    from botocore.client import Config
    from pytest_databases.docker.rustfs import RustfsService

    pytest_plugins = ["pytest_databases.docker.rustfs"]

    def test_with_boto3(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
        scheme = "https" if rustfs_service.secure else "http"
        endpoint_url = f"{scheme}://{rustfs_service.endpoint}"

        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=rustfs_service.access_key,
            aws_secret_access_key=rustfs_service.secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

        # The default bucket is automatically created by the fixture
        response = s3.list_buckets()
        bucket_names = [b["Name"] for b in response["Buckets"]]
        assert rustfs_default_bucket_name in bucket_names

Available Fixtures
------------------

* ``rustfs_access_key``: The access key for RustFS (default: "rustfsadmin").
* ``rustfs_secret_key``: The secret key for RustFS (default: "rustfsadmin").
* ``rustfs_secure``: Whether to use HTTPS for RustFS (default: "false").
* ``rustfs_service``: A fixture that provides a RustFS service.
* ``rustfs_default_bucket_name``: A fixture that provides the default bucket name (automatically created).

Service API
-----------

.. automodule:: pytest_databases.docker.rustfs
   :members:
   :undoc-members:
   :show-inheritance:
