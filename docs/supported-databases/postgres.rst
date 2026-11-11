PostgreSQL
==========

Integration with `PostgreSQL <https://www.postgresql.org/>`_ using the `PostgreSQL Docker Image <https://hub.docker.com/_/postgres>`_, Google's `AlloyDB Omni <https://cloud.google.com/alloydb/omni?hl=en>`_, `pgvector Docker Image <https://hub.docker.com/r/pgvector/pgvector>`_, or `ParadeDB Docker Image <https://hub.docker.com/r/paradedb/paradedb>`_.

Installation
------------

The PostgreSQL service fixtures validate readiness and create per-worker databases using the ``psql`` CLI bundled inside the container image, then confirm the published host port accepts TCP connections, so no Python client driver is required to start the service:

.. code-block:: bash

    pip install pytest-databases

Usage Example
-------------

.. code-block:: python

    import psycopg
    from pytest_databases.docker.postgres import PostgresService

    pytest_plugins = ["pytest_databases.docker.postgres"]


    def test_postgres(postgres_service: PostgresService) -> None:
        with psycopg.connect(postgres_service.dsn) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1
        exit_code, output = postgres_service.exec_sql("SELECT current_database()", tuples_only=True)
        assert exit_code == 0
        assert output.strip().decode() == postgres_service.database


    def test_template_clone(postgres_service: PostgresService) -> None:
        cloned_db = postgres_service.clone_template_database("test_clone_db")
        try:
            assert cloned_db == "test_clone_db"
        finally:
            postgres_service.drop_database_force(cloned_db)

Template Database Acceleration
------------------------------

Suites with heavy migrations or seed data can build the schema once and clone it for each test database. PostgreSQL
creates the clone with ``CREATE DATABASE ... TEMPLATE``, a file-level copy of the template database, so no
migration runs again.

Set ``xdist_postgres_isolation_level`` to ``"template"`` and return the schema from ``postgres_template_setup``. The
first process to reach the container builds the template under a file lock; every other worker waits and clones it.
The service database (``pytest_databases``, or ``pytest_databases_<worker>`` under ``pytest-xdist``) is a fresh
clone, with or without ``pytest-xdist``. Every PostgreSQL family service (versioned PostgreSQL, pgvector, ParadeDB,
AlloyDB Omni) honors these fixtures.

.. code-block:: python

    import pytest
    from pytest_databases.docker.postgres import PostgresService
    from pytest_databases.types import PostgresXdistIsolationLevel

    pytest_plugins = ["pytest_databases.docker.postgres"]


    @pytest.fixture(scope="session")
    def xdist_postgres_isolation_level() -> PostgresXdistIsolationLevel:
        return "template"


    @pytest.fixture(scope="session")
    def postgres_template_setup() -> list[str]:
        return [
            "CREATE TABLE users (id serial PRIMARY KEY, name text)",
            "INSERT INTO users (name) VALUES ('alice'), ('bob')",
        ]


    def test_worker_database(postgres_service: PostgresService) -> None:
        assert postgres_service.database.startswith("pytest_databases")

``postgres_template_setup`` accepts SQL statements, ``pathlib.Path`` objects pointing at ``.sql`` files, or a callable
that receives a :class:`~pytest_databases.docker.postgres.PostgresService` pointed at the staging database. The SQL
text and file contents are hashed into the template name (``pytest_databases_template_<digest>``), so a changed
schema builds a new template even when the container is reused with ``--keep-containers``. A callable cannot be
hashed; return its inputs (migration directories, files, or a version string) from
``postgres_template_fingerprint_sources`` so they become part of the name.

The same helpers are available on :class:`~pytest_databases.docker.postgres.PostgresService` for custom fixtures:

.. code-block:: python

    from pytest_databases.docker.postgres import PostgresService


    def test_custom_template(postgres_service: PostgresService) -> None:
        template = postgres_service.ensure_template(
            "app_template",
            setup_sql="CREATE TABLE items (id serial PRIMARY KEY)",
        )
        worker_db = postgres_service.create_worker_database_from_template(template, "items_test")
        try:
            assert worker_db == "items_test"
        finally:
            postgres_service.drop_database_force(worker_db)

``sweep_worker_databases(prefix)`` drops every non-template database whose name starts with ``prefix`` (``_`` is
matched literally, ``*_staging`` databases are kept). It also drops databases that other workers are still using, so
call it only at the end of a session.

Attaching to an External PostgreSQL Server
------------------------------------------

When CI jobs or shared environments pre-start a PostgreSQL or AlloyDB Omni server outside ``pytest-databases``, use
``postgres_external_service`` or :func:`~pytest_databases.docker.postgres.provide_external_postgres_service` to attach
without requiring a container runtime, ``psql``, or ``psycopg``. Readiness probes, ``"database"`` and ``"template"``
``pytest-xdist`` isolation, and one-shot ``init_sql`` bootstrap run directly over the stdlib PostgreSQL v3 wire
protocol (supporting ``trust``, cleartext, MD5, and ``SCRAM-SHA-256`` authentication).

Set ``POSTGRES_EXTERNAL_HOST`` (and optionally ``POSTGRES_EXTERNAL_PORT``, ``POSTGRES_USER``, and
``POSTGRES_DATABASE``) or call :func:`~pytest_databases.docker.postgres.provide_external_postgres_service` directly in
a custom fixture. Custom container fixtures calling :func:`~pytest_databases.docker.postgres.provide_postgres_service`
can also forward server ``command`` arguments (for example preloading ``pg_stat_statements``), extra ``env``
variables, ``shm_size``, ``mem_limit``, ``volumes``, ``database``, and ``init_sql``.

Available Fixtures
------------------

* ``postgres_host``: The PostgreSQL host address (defaults to ``"127.0.0.1"``, can be overridden with ``POSTGRES_HOST`` environment variable).
* ``postgres_user``: The PostgreSQL superuser name (defaults to ``"postgres"``, env ``POSTGRES_USER``).
* ``postgres_password``: The PostgreSQL superuser password (defaults to ``"super-secret"``).
* ``postgres_database``: Base database name created for family services (defaults to ``"pytest_databases"``, env ``POSTGRES_DATABASE``; ``<postgres_database>_<worker>`` under ``pytest-xdist`` ``"database"`` or ``"template"`` isolation).
* ``postgres_image``: The Docker image to use for PostgreSQL (defaults to ``"postgres:18"``).
* ``postgres_port``: Optional host-side port pin (default ``None``, override via ``POSTGRES_PORT`` env).
* ``postgres_external_host``: Optional hostname or IP of a pre-started PostgreSQL endpoint (default ``None``, env ``POSTGRES_EXTERNAL_HOST``).
* ``postgres_external_port``: Optional TCP port for ``postgres_external_service`` (default ``None``, falling back to ``5432``; env ``POSTGRES_EXTERNAL_PORT``).
* ``postgres_external_service``: Yields an :class:`~pytest_databases.docker.postgres.ExternalPostgresService` connected to ``postgres_external_host`` (skips when unset).
* ``postgres_template_name``: Template name prefix for ``"template"`` isolation (``None`` means ``"pytest_databases_template"``).
* ``postgres_template_setup``: SQL statements, ``.sql`` paths, or a callable that builds the template (default ``None``).
* ``postgres_template_fingerprint_sources``: Extra strings, bytes, files, or directories hashed into the template name (default ``()``).
* ``postgres_template_lock_dir``: Directory for the template lock file (``None`` means the system temp directory).
* ``postgres_template_options``: A :class:`~pytest_databases.docker.postgres.PostgresTemplateOptions` combining the four fixtures above; every family service requests it.
* ``postgres_service``: A fixture that provides a :class:`~pytest_databases.docker.postgres.PostgresService` instance (with ``dsn``, ``connection_config``, and ``exec_sql()``).
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
* ``POSTGRES_USER``: Superuser name configured in PostgreSQL containers and ``postgres_external_service`` (default: ``"postgres"``)
* ``POSTGRES_DATABASE``: Base database name created for PostgreSQL family services and ``postgres_external_service`` (default: ``"pytest_databases"``)
* ``POSTGRES_EXTERNAL_HOST`` and ``POSTGRES_EXTERNAL_PORT``: Hostname/IP and optional TCP port (default ``5432``) used by ``postgres_external_service`` to attach to an existing server
* ``POSTGRES_PORT`` / ``POSTGRES_NN_PORT`` / ``PGVECTOR_PORT`` / ``PGVECTOR_NN_PORT`` / ``PARADEDB_PORT`` / ``PARADEDB_NN_PORT`` / ``ALLOYDB_OMNI_PORT`` / ``ALLOYDB_OMNI_NN_PORT``: Pin a specific host-side port for the matching service fixture. When unset, Docker picks a random free port (the default). See GitHub issue #131.

Service API
-----------

.. automodule:: pytest_databases.docker.postgres
    :members:
    :undoc-members:
    :show-inheritance:
