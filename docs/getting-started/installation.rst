Installation
============

Install ``pytest-databases`` using ``uv`` or ``pip``:

.. code-block:: bash

   pip install pytest-databases

All ``*_service`` container fixtures validate readiness using Python's standard library or tools bundled inside the target container image, so the base ``pytest-databases`` package does not force any database driver dependencies into your environment. Install your application's preferred database or cloud client alongside ``pytest-databases``.

Optional Compatibility Extras
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Compatibility extras remain available for projects that pin ``pytest-databases[<extra>]`` in their dependencies:

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
