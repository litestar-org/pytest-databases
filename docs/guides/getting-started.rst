Getting Started
===============

This guide will help you get started with ``pytest-databases``. We'll cover installation, enabling database plugins, basic usage, and configuration options.

Installation
============

First, install the base package using pip:

.. code-block:: bash

   pip install pytest-databases

Optional Database Support
~~~~~~~~~~~~~~~~~~~~~~~~~

To use ``pytest-databases`` with specific databases, you need to install optional dependencies using "extras". You can install support for one or multiple databases at once.

.. list-table:: Available Database Extras
   :widths: 25 50
   :header-rows: 1

   * - Database
     - Installation Extra
   * - PostgreSQL
     - ``pytest-databases[postgres]``
   * - MySQL
     - ``pytest-databases[mysql]``
   * - MariaDB
     - ``pytest-databases[mariadb]``
   * - Oracle
     - ``pytest-databases[oracle]``
   * - SQL Server
     - ``pytest-databases[sqlserver]``
   * - Google AlloyDB Omni
     - ``pytest-databases[alloydb]``
   * - Google Spanner
     - ``pytest-databases[spanner]``
   * - Google BigQuery
     - ``pytest-databases[bigquery]``
   * - CockroachDB
     - ``pytest-databases[cockroachdb]``
   * - Redis
     - ``pytest-databases[redis]``
   * - Valkey
     - ``pytest-databases[valkey]``
   * - Dragonfly
     - ``pytest-databases[dragonfly]``
   * - KeyDB
     - ``pytest-databases[keydb]``
   * - Elasticsearch
     - ``pytest-databases[elasticsearch]``
   * - Azure Blob Storage
     - ``pytest-databases[azure]``
   * - MinIO
     - ``pytest-databases[minio]``

Example installing multiple extras:

.. code-block:: bash

   pip install pytest-databases[postgres,mysql,redis]


Enabling Database Plugins
=========================

After installing the necessary extras, you need to tell pytest to load the corresponding plugin(s). Add the plugin path(s) to your pytest configuration.

Choose **one** of the following methods:

**1. `pyproject.toml`**:

.. code-block:: toml

   [tool.pytest.ini_options]
   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins = [
       "pytest_databases.docker.postgres",
       "pytest_databases.docker.redis",
   ]

**2. `pytest.ini`**:

.. code-block:: ini

   [pytest]
   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins =
       pytest_databases.docker.postgres
       pytest_databases.docker.redis

**3. `conftest.py`**:

.. code-block:: python

   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins = [
       "pytest_databases.docker.postgres",
       "pytest_databases.docker.redis",
   ]

Basic Usage
===========

Once a plugin is enabled (e.g., PostgreSQL), you can use its fixtures directly in your tests. There are typically two main types of fixtures:

1.  **Service Fixture** (e.g., `postgres_service`): Provides details about the running database service (host, port, credentials, etc.). Useful for connecting with your own client.
2.  **Connection Fixture** (e.g., `postgres_connection`): Provides a ready-to-use connection object (where applicable) to the database service.

.. code-block:: python

   # Assuming you have installed pytest-databases[postgres] and enabled the plugin
   # Also assuming a client like psycopg is installed: pip install psycopg
   import psycopg
   from pytest_databases.docker.postgres import PostgresService

   # Example using the Service Fixture
   def test_connection_with_service_details(postgres_service: PostgresService) -> None:
       conn_str = (
           f"postgresql://{postgres_service.user}:{postgres_service.password}@\"
           f\"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}\"
       )
       with psycopg.connect(conn_str, autocommit=True) as conn:
           with conn.cursor() as cursor:
               cursor.execute("SELECT 1")
               assert cursor.fetchone() == (1,)

   # Example using the Connection Fixture
   def test_with_direct_connection(postgres_connection) -> None:
      # postgres_connection is often a configured client or connection object
      with postgres_connection.cursor() as cursor:
          cursor.execute("CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY, name TEXT);")
          cursor.execute("INSERT INTO users (id, name) VALUES (1, 'Alice');")
          cursor.execute("SELECT name FROM users WHERE id = 1;")
          assert cursor.fetchone() == ('Alice',)

.. _configuration:

Configuration
=============

``pytest-databases`` uses environment variables for configuration. This allows you to override default settings like Docker image tags, usernames, passwords, ports, and database names.

Common Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These variables apply globally to the Docker setup:

*   ``SKIP_DOCKER_COMPOSE=True``: If set, skip trying to manage database containers via Docker Compose. Useful if you manage services externally. (Default: "False")
*   ``USE_LEGACY_DOCKER_COMPOSE=True``: If set, forces the use of the older ``docker-compose`` command instead of ``docker compose``. (Default: "False")
*   ``DOCKER_HOST``: Specifies the host where the Docker daemon is running and where services will be exposed. (Default: "127.0.0.1")

Database-Specific Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each database type has its own set of environment variables for fine-grained control (e.g., ``POSTGRES_USER``, ``POSTGRES_PASSWORD``, ``POSTGRES_DB``, ``POSTGRES_PORT``, ``POSTGRES_TAG`` for PostgreSQL).

Please refer to the documentation for the specific database you are using under the :doc:`../databases/index` section for a complete list of its configuration variables.

Accessing Configuration in Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The effective configuration values (whether defaults or overridden by environment variables) are available as attributes on the service fixture objects:

.. code-block:: python

   from pytest_databases.docker.postgres import PostgresService

   def test_postgres_config_access(postgres_service: PostgresService) -> None:
       # Access configuration values used by the running service
       print(f"Connecting to Postgres user: {postgres_service.user}")
       print(f"Using database: {postgres_service.database}")
       print(f"On host: {postgres_service.host}:{postgres_service.port}")

       # Example assertions (replace with your expected defaults or env overrides)
       assert postgres_service.user == "postgres"
       assert postgres_service.password == "super-secret"
       assert postgres_service.database == "pytest_databases"
       assert postgres_service.host == "127.0.0.1" # Or your DOCKER_HOST override
       assert isinstance(postgres_service.port, int)
       assert postgres_service.port > 0

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


Next Steps
==========

*   Dive deeper into :ref:`configuration` details and database-specific variables.
*   Explore practical :doc:`./examples` demonstrating various testing scenarios.
*   Consult the :doc:`../api/index` reference for detailed information on specific classes and functions.
*   Browse the :doc:`../databases/index` section for specifics on each supported database.
