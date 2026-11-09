Cloudflare KV, R2, and D1 (Miniflare)
=====================================

Integration with `Miniflare <https://github.com/cloudflare/workers-sdk/tree/main/packages/miniflare>`_, the local
simulator behind ``wrangler dev``, for Cloudflare Workers KV, R2, and D1. The container runs Miniflare in a stock
``node:22-slim`` image with one placeholder Worker that binds every configured KV namespace, R2 bucket, and D1
database, and serves two HTTP APIs on port ``8787``:

* The Local Explorer API at ``/cdn-cgi/local/explorer/api``, which answers with the Cloudflare v4 JSON envelope
  (``{"success": true, "errors": [], "messages": [], "result": ...}``) and mirrors the Cloudflare REST paths for KV
  values, R2 objects, and D1 queries.
* An S3-compatible R2 endpoint at ``/cdn-cgi/local/r2/s3`` (AWS Signature Version 4, path-style addressing, region
  ``auto``) that accepts ``cloudflare_access_key_id`` / ``cloudflare_secret_access_key``.

The fixture is clientless: readiness checks and the ``CloudflareService`` helpers use Python's standard library, so
neither ``wrangler`` nor a Cloudflare or AWS SDK is required.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Usage Example
-------------

``CloudflareService`` exposes the resource names this service owns and small helpers for each store. ``kv_get`` and
``r2_get`` return ``None`` for a missing key; ``d1_query`` returns one dictionary per row:

.. code-block:: python

   from pytest_databases.docker.cloudflare import CloudflareService

   pytest_plugins = ["pytest_databases.docker.cloudflare"]


   def test_kv(cloudflare_service: CloudflareService) -> None:
       namespace = cloudflare_service.kv_namespaces[0]
       cloudflare_service.kv_put(namespace, "session/42", "active")
       assert cloudflare_service.kv_get(namespace, "session/42") == b"active"


   def test_r2(cloudflare_service: CloudflareService) -> None:
       bucket = cloudflare_service.r2_buckets[0]
       cloudflare_service.r2_put(bucket, "reports/2026.csv", b"id,total\n1,10\n")
       assert cloudflare_service.r2_get(bucket, "reports/2026.csv") == b"id,total\n1,10\n"


   def test_d1(cloudflare_service: CloudflareService) -> None:
       database = cloudflare_service.d1_databases[0]
       cloudflare_service.d1_query(database, "CREATE TABLE IF NOT EXISTS items (id INTEGER, name TEXT)")
       cloudflare_service.d1_query(database, "INSERT INTO items VALUES (?, ?)", ["1", "widget"])
       assert cloudflare_service.d1_query(database, "SELECT id, name FROM items") == [{"id": 1, "name": "widget"}]

The helpers accept only the names in ``kv_namespaces``, ``r2_buckets``, and ``d1_databases`` and raise
``ValueError`` for any other name. ``d1_query`` sends one statement per call (with several, the emulator returns only
the last statement's rows), and the D1 API accepts string parameters only; SQLite column affinity converts them on
insert. Other Local Explorer endpoints are available under ``cloudflare_service.api_base_url``.

R2 through an S3 client
-----------------------

Point any S3 client at ``r2_s3_endpoint_url`` with path-style addressing and region ``auto``. With ``boto3``
installed in your project:

.. code-block:: python

   import boto3
   from botocore.config import Config

   from pytest_databases.docker.cloudflare import CloudflareService

   pytest_plugins = ["pytest_databases.docker.cloudflare"]


   def test_r2_s3(cloudflare_service: CloudflareService) -> None:
       s3 = boto3.client(
           "s3",
           endpoint_url=cloudflare_service.r2_s3_endpoint_url,
           aws_access_key_id=cloudflare_service.access_key_id,
           aws_secret_access_key=cloudflare_service.secret_access_key,
           region_name="auto",
           config=Config(s3={"addressing_style": "path"}),
       )
       bucket = cloudflare_service.r2_buckets[0]
       s3.put_object(Bucket=bucket, Key="hello.txt", Body=b"hello")
       assert s3.get_object(Bucket=bucket, Key="hello.txt")["Body"].read() == b"hello"

The S3 endpoint serves only the configured buckets; it cannot create new ones.

Configuring resources
---------------------

Override the resource fixtures to bind more namespaces, buckets, or databases. Each fixture returns a tuple of names
(default ``("default",)``):

.. code-block:: python

   import pytest


   @pytest.fixture(scope="session")
   def cloudflare_kv_namespaces() -> tuple[str, ...]:
       return ("sessions", "cache")


   @pytest.fixture(scope="session")
   def cloudflare_r2_buckets() -> tuple[str, ...]:
       return ("uploads",)

Startup and network access
--------------------------

On first start the container installs ``ca-certificates`` with ``apt-get`` (``workerd``, Miniflare's runtime, needs
system CA certificates) and runs ``npm install miniflare@<cloudflare_miniflare_version>``, which downloads about
200 MB including the ``workerd`` binary. The first start therefore needs network access to the Debian and npm
registries and usually takes one to two minutes; ``cloudflare_startup_timeout`` (default ``300`` seconds, env
``CLOUDFLARE_STARTUP_TIMEOUT``) bounds the wait. Containers reused within a session start instantly.

The installs are skipped when the image already provides them. To start offline or faster, build an image that has the
certificates and Miniflare in ``/app`` and point ``CLOUDFLARE_IMAGE`` (or the ``cloudflare_image`` fixture) at it:

.. code-block:: docker

   FROM node:22-slim
   RUN apt-get update \
       && apt-get install -y --no-install-recommends ca-certificates \
       && rm -rf /var/lib/apt/lists/*
   WORKDIR /app
   RUN npm install --no-audit --no-fund miniflare@5.20261104.0-beta

The image must be glibc-based (``workerd`` does not run on Alpine/musl) and provide Node.js 22 or later.

Isolation
---------

With the default ``xdist_cloudflare_isolation_level`` (``database``), all pytest-xdist workers share one container
named ``cloudflare``. It binds every configured name once per worker with a ``_<worker>`` suffix (``default_0``,
``default_1``, ...), and each worker's ``CloudflareService`` lists only its own names, so workers never see each
other's keys, objects, or tables. Without pytest-xdist the names are used as given. With ``server`` each worker
starts its own container named ``cloudflare_<worker>`` with the names as given.

The shared container's bindings are fixed when it starts. If a container kept from an earlier run (for example with
``--keep-containers``) does not bind every name a worker needs, the fixture fails with a message asking you to remove
the container.

Limitations
-----------

* Only Miniflare 5 serves the Local Explorer and R2 S3 paths; Miniflare 4 routes them to the user Worker. Miniflare 5
  is published under the npm ``beta`` tag, so ``cloudflare_miniflare_version`` pins ``5.20261104.0-beta`` (env
  ``CLOUDFLARE_MINIFLARE_VERSION``). The Local Explorer API is marked unsafe and experimental upstream and can change
  between Miniflare releases.
* The first start needs network access (see above) unless a prebuilt image is used.
* Only KV, R2, and D1 are exposed. The placeholder Worker answers every request with ``ok``; there is no API to deploy
  or run your own Worker code, and Durable Objects, Queues, Workflows, and other bindings are not configured.
* Data lives in the container (``/data``) and is discarded with it.

Available Fixtures
------------------

* ``cloudflare_image``: Node.js image that runs Miniflare (default ``node:22-slim``, env ``CLOUDFLARE_IMAGE``).
* ``cloudflare_miniflare_version``: Miniflare version installed when the image lacks it (env
  ``CLOUDFLARE_MINIFLARE_VERSION``).
* ``cloudflare_kv_namespaces``, ``cloudflare_r2_buckets``, ``cloudflare_d1_databases``: resource names (default
  ``("default",)``).
* ``cloudflare_access_key_id``, ``cloudflare_secret_access_key``: credentials for the R2 S3 endpoint (defaults
  ``pytest-databases`` / ``pytest-databases-secret``, env ``CLOUDFLARE_ACCESS_KEY_ID`` /
  ``CLOUDFLARE_SECRET_ACCESS_KEY``).
* ``cloudflare_startup_timeout``: startup timeout in seconds (default ``300``, env ``CLOUDFLARE_STARTUP_TIMEOUT``).
* ``xdist_cloudflare_isolation_level``: ``database`` (default) or ``server``.
* ``cloudflare_service``: the running ``CloudflareService``.

Service API
-----------

.. automodule:: pytest_databases.docker.cloudflare
   :members:
