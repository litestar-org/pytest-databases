Pytest Databases
================
.. toctree::
   :maxdepth: 2
   :caption: Contents:
   :hidden:

   README
   databases/index
   getting-started

Pytest Databases is a powerful testing utility that provides ready-made database fixtures for your pytest tests. It simplifies the process of setting up and managing database connections during testing, making it easier to write and maintain database-driven tests.

Features
========

* 🚀 Easy-to-use database fixtures
* 🔄 Support for multiple database types
* 🐳 Docker integration for isolated testing environments
* ⚡ Fast and efficient test execution
* 🔧 Highly configurable
* 📦 Lightweight and dependency-aware

Supported Databases
===================

.. list-table::
   :widths: 25 25 50
   :header-rows: 1

   * - Database
     - Supported Versions
     - Docker Image / Emulator / Driver Link
   * - PostgreSQL
     - 11-17
     - `Official PostgreSQL Docker Image <https://hub.docker.com/_/postgres>`_
   * - MySQL
     - 5.6, 5.7, 8
     - `Official MySQL Docker Image <https://hub.docker.com/_/mysql>`_
   * - MariaDB
     - Latest
     - `Official MariaDB Docker Image <https://hub.docker.com/_/mariadb>`_
   * - Oracle
     - 18c XE, 23c Free
     - `Oracle Database Docker Images <https://hub.docker.com/r/oracle/database/>`_
   * - SQL Server
     - 2022
     - `Microsoft SQL Server Docker Image <https://hub.docker.com/_/microsoft-mssql-server>`_
   * - Google AlloyDB Omni
     - Omni Installation
     - `AlloyDB Omni Documentation <https://cloud.google.com/alloydb/omni/docs/introduction>`_
   * - Google Spanner
     - Latest Cloud Emulator
     - `Spanner Emulator <https://cloud.google.com/spanner/docs/emulator>`_
   * - Google BigQuery
     - Unofficial Emulator
     - `BigQuery Emulator (Unofficial) <https://github.com/goccy/bigquery-emulator>`_
   * - CockroachDB
     - Latest
     - `Official CockroachDB Docker Image <https://hub.docker.com/r/cockroachdb/cockroach/>`_
   * - Redis
     - Latest
     - `Official Redis Docker Image <https://hub.docker.com/_/redis>`_
   * - Elasticsearch
     - 7, 8
     - `Elasticsearch Docker Images <https://www.docker.elastic.co/>`_
   * - Azure Blob Storage
     - Azurite Emulator
     - `Azurite Docker Image <https://hub.docker.com/_/microsoft-azure-storage-azurite>`_
   * - MinIO
     - Latest
     - `Official MinIO Docker Image <https://hub.docker.com/r/minio/minio>`_

Quick Start
===========

**Installation**

Install the base package using pip:

.. code-block:: bash

   pip install pytest-databases

To include support for specific databases, install the package with extras. For example, to add PostgreSQL support:

.. code-block:: bash

   pip install pytest-databases[postgres]

You can specify multiple databases:

.. code-block:: bash

   pip install pytest-databases[postgres,mysql,redis]

See the :doc:`getting-started` guide for a full list of available extras and detailed installation instructions.

**Basic Usage**

1.  **Configure pytest:** Add the desired database plugin to your `pytest.ini` or `conftest.py`. For example, for PostgreSQL:

    .. code-block:: ini
       :caption: pytest.ini

       [pytest]
       pytest_plugins = pytest_databases.docker.postgres

    Or in `conftest.py`:

    .. code-block:: python
       :caption: conftest.py

       pytest_plugins = ["pytest_databases.docker.postgres"]

2.  **Use fixtures in your tests:** The plugin provides fixtures like `postgres_service` (for service details) and `postgres_connection` (for a ready-to-use database connection).

    .. code-block:: python

       from pytest_databases.docker.postgres import PostgresService
       import psycopg

       # postgres_service provides connection details for the running service
       def test_service_connection(postgres_service: PostgresService) -> None:
            """Example test connecting directly using service details."""
            conn_str = (
                f"postgresql://{postgres_service.user}:{postgres_service.password}@"
                f"{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
            )
            with psycopg.connect(conn_str, autocommit=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    assert cursor.fetchone() == (1,)

       # postgres_connection provides a ready-made connection object
       def test_direct_connection_fixture(postgres_connection: psycopg.Connection) -> None:
            """Example test using the direct connection fixture."""
            with postgres_connection.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS foo (id INT);")
                cursor.execute("INSERT INTO foo (id) VALUES (1);")
                cursor.execute("SELECT COUNT(*) FROM foo;")
                assert cursor.fetchone() == (1,)

For more detailed examples and advanced usage, refer to the :doc:`getting-started` details and the :doc:`databases/index` documentation.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
