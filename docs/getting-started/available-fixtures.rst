Available Fixtures
==================

Each database plugin provides specific fixtures. Generally, for a database named ``X``, you will find:

*   ``X_service``: The main service fixture, providing connection details. For databases supporting multiple versions (e.g., PostgreSQL, MySQL, Elasticsearch), version-specific service fixtures like ``postgres_16_service`` are also available.
*   ``X_connection``: A ready-to-use connection/client fixture (if applicable for the database type). Version-specific connection fixtures (e.g., ``postgres_16_connection``) are also provided where relevant.

Here is a summary table (refer to individual database pages under :doc:`../databases/index` for full details and version specifics):

.. list-table:: Fixture Summary by Database
   :widths: 20 40 40
   :header-rows: 1

   * - Database
     - Example Service Fixture(s)
     - Example Connection Fixture(s)
   * - PostgreSQL
     - ``postgres_service``, ``postgres_16_service``
     - ``postgres_connection``, ``postgres_16_connection``
   * - MySQL
     - ``mysql_service``, ``mysql_8_service``
     - ``mysql_connection``, ``mysql_8_connection``
   * - MariaDB
     - ``mariadb_service``
     - ``mariadb_connection``
   * - Oracle
     - ``oracle_service``, ``oracle_23ai_service``
     - ``oracle_connection``, ``oracle_23ai_connection``
   * - SQL Server
     - ``mssql_service``
     - ``mssql_connection``
   * - AlloyDB
     - ``alloydb_omni_service``
     - ``alloydb_omni_connection``
   * - Spanner
     - ``spanner_service``
     - ``spanner_connection``
   * - BigQuery
     - ``bigquery_service``
     - ``bigquery_connection``
   * - CockroachDB
     - ``cockroachdb_service``
     - ``cockroachdb_connection``
   * - Redis
     - ``redis_service``
     - ``redis_connection``
   * - Valkey
     - ``valkey_service``
     - ``valkey_connection``
   * - Dragonfly
     - ``dragonfly_service``
     - ``dragonfly_connection``
   * - KeyDB
     - ``keydb_service``
     - ``keydb_connection``
   * - Elasticsearch
     - ``elasticsearch_service``, ``elasticsearch_8_service``
     - ``elasticsearch_connection``, ``elasticsearch_8_connection``
   * - Azure Blob Storage
     - ``azure_blob_service``
     - ``azure_blob_connection``
   * - MinIO
     - ``minio_service``
     - ``minio_connection``
