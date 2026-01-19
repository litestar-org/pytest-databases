PostgreSQL
==========

Integration with `PostgreSQL <https://www.postgresql.org/>`_ using the `PostgreSQL Docker Image <https://hub.docker.com/_/postgres>`_, Google's `AlloyDB Omni <https://cloud.google.com/alloydb/omni?hl=en>`_ or `pgvector Docker Image <https://hub.docker.com/r/ankane/pgvector>`_

Installation
------------

.. code-block:: bash

    pip install pytest-databases[postgres]

Usage Example
-------------

.. code-block:: python

    import pytest
    import psycopg
    from pytest_databases.docker.postgres import PostgresService

    pytest_plugins = ["pytest_databases.docker.postgres"]

    def test(postgres_service: PostgresService) -> None:
        with psycopg.connect(
            f"postgresql://{postgres_service.user}:{postgres_service.password}@{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
        ) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

    def test(postgres_connection: psycopg.Connection) -> None:
        postgres_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = postgres_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1

Available Fixtures
------------------

* ``postgres_host``: The PostgreSQL host address (defaults to "127.0.0.1", can be overridden with ``POSTGRES_HOST`` environment variable).
* ``postgres_user``: The PostgreSQL user.
* ``postgres_password``: The PostgreSQL password.
* ``postgres_database``: The PostgreSQL database name to use.
* ``postgres_image``: The Docker image to use for PostgreSQL.
* ``postgres_service``: A fixture that provides a PostgreSQL service.
* ``postgres_connection``: A fixture that provides a PostgreSQL connection.

The following version-specific fixtures are also available:

* ``alloydb_omni_image``, ``alloydb_omni_service``, ``alloydb_omni_connection``: Latest Available AlloyDB Omni 16 Docker image.
* ``postgres_11_image``, ``postgres_11_service``, ``postgres_11_connection``: PostgreSQL 11.x
* ``postgres_12_image``, ``postgres_12_service``, ``postgres_12_connection``: PostgreSQL 12.x
* ``postgres_13_image``, ``postgres_13_service``, ``postgres_13_connection``: PostgreSQL 13.x
* ``postgres_14_image``, ``postgres_14_service``, ``postgres_14_connection``: PostgreSQL 14.x
* ``postgres_15_image``, ``postgres_15_service``, ``postgres_15_connection``: PostgreSQL 15.x
* ``postgres_16_image``, ``postgres_16_service``, ``postgres_16_connection``: PostgreSQL 16.x
* ``postgres_17_image``, ``postgres_17_service``, ``postgres_17_connection``: PostgreSQL 17.x
* ``postgres_18_image``, ``postgres_18_service``, ``postgres_18_connection``: PostgreSQL 18.x
* ``pgvector_image``, ``pgvector_service``. ``pgvector_connection``: Latest Available pgvector Docker image.

Configuration
-------------

PostgreSQL services can be configured using environment variables:

* ``POSTGRES_HOST``: The host address for the PostgreSQL container (default: "127.0.0.1")

Example usage with custom host:

.. code-block:: bash

    export POSTGRES_HOST="192.168.1.100"
    pytest

Service API
-----------

.. automodule:: pytest_databases.docker.postgres
    :members:
    :undoc-members:
    :show-inheritance:
