Embedded PostgreSQL
===================

Runs a real `PostgreSQL <https://www.postgresql.org/>`_ server from local binaries, without Docker or Podman.

Overview
--------

``pytest_databases.embedded.postgres`` runs ``initdb`` and ``postgres`` in a temporary directory and serves the
cluster on a loopback TCP port. The cluster uses ``trust`` authentication (``password`` defaults to ``""`` and is
reflected in ``dsn`` and ``connection_config`` whenever non-empty) and has Unix-domain sockets
disabled, plus non-durable settings (``fsync = off``, ``synchronous_commit = off``, ``full_page_writes = off``) that
suit throwaway test data. The fixture runs its own SQL over a stdlib PostgreSQL v3 wire client (which supports ``trust``, cleartext, MD5, and
``SCRAM-SHA-256`` authentication and also powers ``postgres_external_service`` in :doc:`postgres`), so neither ``psql``
nor a Python driver is required. ``EmbeddedPostgresService`` satisfies :class:`~pytest_databases.PostgresServiceProtocol`
alongside ``PostgresService`` and ``ExternalPostgresService``. Any PostgreSQL client (``psycopg``, ``asyncpg``, SQLAlchemy, SQLSpec) connects with
``dsn`` or ``connection_config``.

Installation
------------

Install the ``embedded-postgres`` extra (see :doc:`../getting-started/installation` for other installers). It pulls
in ``pgembed`` on Python 3.12+ and ``pgserver`` on Python 3.11, which ship the server binaries:

.. code-block:: bash

    pip install "pytest-databases[embedded-postgres]"

Without the extra, the binaries are looked up in this order: the ``embedded_postgres_bin_dir`` fixture, the
``PG_BIN_DIR`` environment variable, the ``pgembed`` / ``pgserver`` packages, the ``PATH``, ``pg_config --bindir``,
and common install directories (``/usr/lib/postgresql/*/bin``, Homebrew ``postgresql@*``, ``/usr/pgsql-*``). Only
``initdb`` and ``postgres`` are required; ``pg_ctl`` is used for shutdown when present.

Usage Example
-------------

.. code-block:: python

    import psycopg
    from pytest_databases.embedded.postgres import EmbeddedPostgresService

    pytest_plugins = ["pytest_databases.embedded.postgres"]


    def test_embedded_postgres(embedded_postgres_service: EmbeddedPostgresService) -> None:
        with psycopg.connect(embedded_postgres_service.dsn) as conn:
            row = conn.execute("SELECT 1").fetchone()
            assert row is not None and row[0] == 1


    def test_exec_sql(embedded_postgres_service: EmbeddedPostgresService) -> None:
        exit_code, output = embedded_postgres_service.exec_sql("SELECT current_database()", tuples_only=True)
        assert exit_code == 0
        assert output.strip().decode() == embedded_postgres_service.database

``exec_sql(sql, *, database=None, tuples_only=False, timeout=30.0)`` returns ``(exit_code, output)`` as
``tuple[int, bytes]``, matching :meth:`~pytest_databases.docker.postgres.PostgresService.exec_sql`: one line per row
with ``|`` between columns, exit code ``1`` for an SQL error, and ``2`` for a connection failure.

Portable PostgreSQL Backend Switching
-------------------------------------

Use the ``postgres_any_service`` fixture typed as :class:`~pytest_databases.PostgresServiceProtocol` to write suites
that target either containerized PostgreSQL or local embedded binaries:

.. code-block:: python

    from pytest_databases import PostgresServiceProtocol

    pytest_plugins = ["pytest_databases.embedded.postgres"]


    def test_portable_postgres(postgres_any_service: PostgresServiceProtocol) -> None:
        exit_code, output = postgres_any_service.exec_sql("SELECT 1", tuples_only=True, timeout=30.0)
        assert exit_code == 0
        assert output.strip() == b"1"

Switch backends with ``--postgres-backend=embedded``, ini ``postgres_backend = "embedded"``, or
``PYTEST_DATABASES_POSTGRES_BACKEND=embedded`` (precedence ``CLI -> ini -> env -> "docker"``). Suites registering
only ``pytest_databases.docker.postgres`` still resolve ``embedded`` lazily via ``resolve_postgres_binaries()`` (honoring
``PG_BIN_DIR``) without probing Docker or Podman.

Isolation and Template Databases
--------------------------------

``xdist_embedded_postgres_isolation_level`` controls how databases are created:

* ``"template"`` (the default): a template database is built once from ``embedded_postgres_template_setup`` and the
  service database is cloned from it. Under ``pytest-xdist`` every worker shares one cluster and gets its own clone
  (``pytest_databases_<worker>``); without xdist the single clone is ``pytest_databases``.
* ``"database"``: as above, but each database starts empty.
* ``"server"``: each worker starts its own cluster.

The shared cluster is stopped and its data directory removed when the last worker finishes; worker databases are
dropped at teardown.

.. code-block:: python

    import pytest
    from pytest_databases.embedded.postgres import EmbeddedPostgresService

    pytest_plugins = ["pytest_databases.embedded.postgres"]


    @pytest.fixture(scope="session")
    def embedded_postgres_template_setup() -> list[str]:
        return [
            "CREATE TABLE users (id serial PRIMARY KEY, username text NOT NULL)",
            "INSERT INTO users (username) VALUES ('alice')",
        ]


    def test_worker_database(embedded_postgres_service: EmbeddedPostgresService) -> None:
        exit_code, output = embedded_postgres_service.exec_sql("SELECT count(*) FROM users")
        assert exit_code == 0
        assert output == b"1"

The setup can also be a list of ``pathlib.Path`` objects pointing at ``.sql`` files, or a callable that receives the
staging service:

.. code-block:: python

    from collections.abc import Callable

    import pytest
    from pytest_databases.embedded.postgres import EmbeddedPostgresService


    @pytest.fixture(scope="session")
    def embedded_postgres_template_setup() -> Callable[[EmbeddedPostgresService], None]:
        def setup(service: EmbeddedPostgresService) -> None:
            exit_code, output = service.exec_sql("CREATE TABLE users (id serial PRIMARY KEY)")
            assert exit_code == 0, output

        return setup

SQL text and file contents are hashed into the template name, so a changed schema builds a new template. A callable
cannot be hashed; return its inputs from ``embedded_postgres_template_fingerprint_sources``. The template helpers
(``ensure_template()``, ``create_worker_database_from_template()``, ``clone_template_database()``,
``drop_database_force()``, ``sweep_worker_databases()``) work as described in :doc:`postgres`.

Available Fixtures
------------------

* ``embedded_postgres_service``: An :class:`~pytest_databases.embedded.postgres.EmbeddedPostgresService` pointed at
  this process's database (with ``password=""`` default under ``trust`` auth).
* ``postgres_any_service``: Cross-backend session fixture yielding a :class:`~pytest_databases.PostgresServiceProtocol`
  instance (delegating to ``embedded_postgres_service`` when ``--postgres-backend=embedded``).
* ``embedded_postgres_user``: Superuser name (defaults to ``"postgres"``).
* ``embedded_postgres_database``: Base name of the yielded database (defaults to ``"pytest_databases"``;
  ``pytest_databases_<worker>`` under xdist).
* ``embedded_postgres_port``: Server port (defaults to ``0``, a free port).
* ``embedded_postgres_bin_dir``: Directory holding ``initdb`` / ``postgres`` (defaults to ``None``, which searches the
  locations listed above).
* ``xdist_embedded_postgres_isolation_level``: ``"template"`` (default), ``"database"``, or ``"server"``.
* ``embedded_postgres_template_name``: Template name prefix (``None`` means ``"pytest_databases_template"``).
* ``embedded_postgres_template_setup``: SQL statements, ``.sql`` paths, or a callable that builds the template.
* ``embedded_postgres_template_fingerprint_sources``: Extra strings, bytes, files, or directories hashed into the
  template name.
* ``embedded_postgres_template_lock_dir``: Directory for the template lock file (``None`` means the system temp
  directory).

For a cluster outside the fixture, use ``provide_embedded_postgres_service(..., password="", init_sql=None)`` and
``ensure_template(..., init_sql=...)`` for extension initialization prior to user template setup. Its
``cleanup_mode="delete"`` removes the temporary data directory on exit and ``"keep"`` leaves it for inspection; a
``data_dir`` you pass is never deleted.

Service API
-----------

.. automodule:: pytest_databases.embedded.postgres
    :members:
    :undoc-members:
    :show-inheritance:
    :exclude-members: PostgresServiceProtocol
