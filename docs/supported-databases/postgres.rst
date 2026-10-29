PostgreSQL
==========

Integration with `PostgreSQL <https://www.postgresql.org/>`_ using the `PostgreSQL Docker Image <https://hub.docker.com/_/postgres>`_, Google's `AlloyDB Omni <https://cloud.google.com/alloydb/omni?hl=en>`_, `pgvector Docker Image <https://hub.docker.com/r/pgvector/pgvector>`_, or `ParadeDB Docker Image <https://hub.docker.com/r/paradedb/paradedb>`_.

Installation
------------

The PostgreSQL service fixtures validate readiness and create per-worker databases using the ``psql`` CLI bundled inside the container image, so no Python client driver is required to start the service:

.. code-block:: bash

    pip install pytest-databases

Usage Example
-------------

.. code-block:: python

    import psycopg
    from pytest_databases.docker.postgres import PostgresService

    pytest_plugins = ["pytest_databases.docker.postgres"]


    def test_postgres(postgres_service: PostgresService) -> None:
        with psycopg.connect(
            f"postgresql://{postgres_service.user}:{postgres_service.password}"
            f"@{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
        ) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1


    def test_template_clone(postgres_service: PostgresService) -> None:
        cloned_db = postgres_service.clone_template_database("test_clone_db")
        try:
            assert cloned_db == "test_clone_db"
        finally:
            postgres_service.drop_database_force(cloned_db)

Available Fixtures
------------------

* ``postgres_host``: The PostgreSQL host address (defaults to ``"127.0.0.1"``, can be overridden with ``POSTGRES_HOST`` environment variable).
* ``postgres_user``: The PostgreSQL user.
* ``postgres_password``: The PostgreSQL password.
* ``postgres_image``: The Docker image to use for PostgreSQL (defaults to ``"postgres:18"``).
* ``postgres_port``: Optional host-side port pin (default ``None``, override via ``POSTGRES_PORT`` env).
* ``postgres_service``: A fixture that provides a :class:`~pytest_databases.docker.postgres.PostgresService` instance.
* ``postgres_connection``: Deprecated fixture that yields a ``psycopg.Connection``.

The following version-specific fixtures are also available. Each has its own
``*_port`` fixture and matching env var so multiple versions can be pinned in
the same session without colliding:

* ``postgres_11_service``, ``postgres_11_connection``, ``postgres_11_port`` (env: ``POSTGRES_11_PORT``)
* ``postgres_12_service``, ``postgres_12_connection``, ``postgres_12_port`` (env: ``POSTGRES_12_PORT``)
* ``postgres_13_service``, ``postgres_13_connection``, ``postgres_13_port`` (env: ``POSTGRES_13_PORT``)
* ``postgres_14_service``, ``postgres_14_connection``, ``postgres_14_port`` (env: ``POSTGRES_14_PORT``)
* ``postgres_15_service``, ``postgres_15_connection``, ``postgres_15_port`` (env: ``POSTGRES_15_PORT``)
* ``postgres_16_service``, ``postgres_16_connection``, ``postgres_16_port`` (env: ``POSTGRES_16_PORT``)
* ``postgres_17_service``, ``postgres_17_connection``, ``postgres_17_port`` (env: ``POSTGRES_17_PORT``)
* ``postgres_18_service``, ``postgres_18_connection``, ``postgres_18_port`` (env: ``POSTGRES_18_PORT``)

pgvector
^^^^^^^^

* ``pgvector_image``, ``pgvector_service``, ``pgvector_connection``, ``pgvector_port`` (env: ``PGVECTOR_PORT``) — default image ``pgvector/pgvector:pg18``
* ``pgvector_13_service``, ``pgvector_13_connection``, ``pgvector_13_port`` (env: ``PGVECTOR_13_PORT``)
* ``pgvector_14_service``, ``pgvector_14_connection``, ``pgvector_14_port`` (env: ``PGVECTOR_14_PORT``)
* ``pgvector_15_service``, ``pgvector_15_connection``, ``pgvector_15_port`` (env: ``PGVECTOR_15_PORT``)
* ``pgvector_16_service``, ``pgvector_16_connection``, ``pgvector_16_port`` (env: ``PGVECTOR_16_PORT``)
* ``pgvector_17_service``, ``pgvector_17_connection``, ``pgvector_17_port`` (env: ``PGVECTOR_17_PORT``)
* ``pgvector_18_service``, ``pgvector_18_connection``, ``pgvector_18_port`` (env: ``PGVECTOR_18_PORT``)

ParadeDB
^^^^^^^^

ParadeDB extends PostgreSQL with BM25 full-text search and analytics extensions.

* ``paradedb_image``, ``paradedb_service``, ``paradedb_connection``, ``paradedb_port`` (env: ``PARADEDB_PORT``) — default image ``paradedb/paradedb:latest-pg18``
* ``paradedb_15_service``, ``paradedb_15_connection``, ``paradedb_15_port`` (env: ``PARADEDB_15_PORT``)
* ``paradedb_16_service``, ``paradedb_16_connection``, ``paradedb_16_port`` (env: ``PARADEDB_16_PORT``)
* ``paradedb_17_service``, ``paradedb_17_connection``, ``paradedb_17_port`` (env: ``PARADEDB_17_PORT``)
* ``paradedb_18_service``, ``paradedb_18_connection``, ``paradedb_18_port`` (env: ``PARADEDB_18_PORT``)

AlloyDB Omni
^^^^^^^^^^^^

* ``alloydb_omni_image``, ``alloydb_omni_service``, ``alloydb_omni_connection``, ``alloydb_omni_port`` (env: ``ALLOYDB_OMNI_PORT``) — default image ``gcr.io/alloydb-omni/alloydbomni:18``
* ``alloydb_omni_15_service``, ``alloydb_omni_15_connection``, ``alloydb_omni_15_port`` (env: ``ALLOYDB_OMNI_15_PORT``)
* ``alloydb_omni_16_service``, ``alloydb_omni_16_connection``, ``alloydb_omni_16_port`` (env: ``ALLOYDB_OMNI_16_PORT``)
* ``alloydb_omni_17_service``, ``alloydb_omni_17_connection``, ``alloydb_omni_17_port`` (env: ``ALLOYDB_OMNI_17_PORT``)
* ``alloydb_omni_18_service``, ``alloydb_omni_18_connection``, ``alloydb_omni_18_port`` (env: ``ALLOYDB_OMNI_18_PORT``)

Configuration
-------------

PostgreSQL services can be configured using environment variables:

* ``POSTGRES_HOST``: The host address for the PostgreSQL container (default: ``"127.0.0.1"``)
* ``POSTGRES_PORT`` / ``POSTGRES_NN_PORT`` / ``PGVECTOR_PORT`` / ``PGVECTOR_NN_PORT`` / ``PARADEDB_PORT`` / ``PARADEDB_NN_PORT`` / ``ALLOYDB_OMNI_PORT`` / ``ALLOYDB_OMNI_NN_PORT``: Pin a specific host-side port for the matching service fixture. When unset, Docker picks a random free port (the default). See GitHub issue #131.

Service API
-----------

.. automodule:: pytest_databases.docker.postgres
    :members:
    :undoc-members:
    :show-inheritance:
