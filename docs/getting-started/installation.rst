Installation
============

Install ``pytest-databases`` using ``uv`` or ``pip``:

.. code-block:: bash

   pip install pytest-databases

All ``*_service`` container fixtures validate readiness using Python's standard library or tools bundled inside the target container image, so the base ``pytest-databases`` package does not force any database driver dependencies into your environment. Install your application's preferred database or cloud client alongside ``pytest-databases``.

Optional Extras
~~~~~~~~~~~~~~~

The embedded PostgreSQL service can be installed via the ``embedded-postgres`` extra:

.. code-block:: bash

   pip install "pytest-databases[embedded-postgres]"

.. deprecated:: 0.20.0
   Database driver and cloud SDK compatibility extras (e.g. ``pytest-databases[postgres]``,
   ``pytest-databases[redis]``, etc.) are deprecated in v0.20.0 and will be removed in v1.0.0.
   Because all container services validate readiness without third-party client libraries, install
   the base package (``pip install pytest-databases``) and bring your application's preferred client
   drivers directly. The ``pytest-databases[embedded-postgres]`` extra remains fully supported.

Legacy Compatibility Extras
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Legacy compatibility extras remain available during the v0.20.x deprecation window for projects that pin ``pytest-databases[<extra>]`` in their dependencies:

.. list-table:: Available Compatibility Extras
   :widths: 30 50
   :header-rows: 1

   * - Provider / Service
     - Installation Extra
   * - PostgreSQL / pgvector / ParadeDB
     - ``pytest-databases[postgres]``
   * - Google AlloyDB Omni
     - ``pytest-databases[alloydb]``
   * - MySQL
     - ``pytest-databases[mysql]``
   * - MariaDB
     - ``pytest-databases[mariadb]``
   * - Dolt
     - ``pytest-databases[dolt]``
   * - Oracle Database / ADB-Free
     - ``pytest-databases[oracle]``
   * - Microsoft SQL Server
     - ``pytest-databases[mssql]``
   * - IBM Db2 Community Edition
     - ``pytest-databases[db2]``
   * - Google Cloud Spanner
     - ``pytest-databases[spanner]``
   * - Google BigQuery
     - ``pytest-databases[bigquery]``
   * - Snowflake (Embucket)
     - ``pytest-databases[snowflake]``
   * - CockroachDB
     - ``pytest-databases[cockroachdb]``
   * - YugabyteDB
     - ``pytest-databases[yugabyte]``
   * - MongoDB
     - ``pytest-databases[mongodb]``
   * - GizmoSQL
     - ``pytest-databases[gizmosql]``
   * - Redis / Dragonfly / KeyDB
     - ``pytest-databases[redis]``
   * - Valkey
     - ``pytest-databases[valkey]``
   * - Elasticsearch
     - ``pytest-databases[elasticsearch]``
   * - Azure Blob Storage (Azurite)
     - ``pytest-databases[azure-blob]``
   * - MinIO
     - ``pytest-databases[minio]``
   * - RustFS
     - ``pytest-databases[rustfs]``
   * - Redpanda (Kafka)
     - ``pytest-databases[redpanda]``
   * - LocalStack (AWS)
     - ``pytest-databases[localstack]``
   * - Google Cloud Pub/Sub
     - ``pytest-databases[pubsub]``
   * - RabbitMQ (AMQP)
     - ``pytest-databases[rabbitmq]``
   * - Floci Cloud Emulators (GCP / OCI / AWS / Azure)
     - ``pytest-databases[floci]``
