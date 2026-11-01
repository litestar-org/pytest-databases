Embedded PostgreSQL
===================

Integration with embedded and non-containerized `PostgreSQL <https://www.postgresql.org/>`_ using `pgembed <https://pypi.org/project/pgembed/>`_ or host-installed PostgreSQL binaries.

Overview
--------

``pytest_databases.embedded.postgres`` provides a lightweight, zero-Docker alternative to containerized PostgreSQL testing services. It manages a genuine native PostgreSQL server in user space, binding to a local loopback port and Unix domain socket in ~150 milliseconds.

Key capabilities:

* **Zero-Container Execution:** Runs without Docker, Podman, root access, or background daemon setup.
* **100% Wire Protocol Compatibility:** Works out of the box with standard PostgreSQL client drivers including ``psycopg``, ``asyncpg``, ``SQLAlchemy``, and ``SQLSpec``.
* **Feature Parity with Docker Service:** Implements the exact same connection interface, ``exec_psql`` execution probe, and copy-on-write template database acceleration.
* **Multi-Worker Isolation:** Seamlessly supports ``pytest-xdist`` parallel test execution via template database cloning or per-worker database creation.

Installation
------------

Install ``pytest-databases`` with the optional ``embedded-postgres`` extra (or install ``pgembed`` directly):

.. code-block:: bash

    pip install "pytest-databases[embedded-postgres]"

If PostgreSQL binaries (``initdb``, ``postgres``, ``psql``) are already installed on your system PATH or specified via the ``PG_BIN_DIR`` environment variable, ``pytest-databases`` uses them directly without requiring additional dependencies.

Usage Example
-------------

.. code-block:: python

    import psycopg
    from pytest_databases.embedded.postgres import EmbeddedPostgresService

    pytest_plugins = ["pytest_databases.embedded.postgres"]


    def test_embedded_postgres(embedded_postgres_service: EmbeddedPostgresService) -> None:
        with psycopg.connect(
            f"postgresql://{embedded_postgres_service.user}:{embedded_postgres_service.password}"
            f"@{embedded_postgres_service.host}:{embedded_postgres_service.port}/{embedded_postgres_service.database}"
        ) as conn:
            row = conn.execute("SELECT 1").fetchone()
            assert row is not None and row[0] == 1


    def test_clone_database(embedded_postgres_service: EmbeddedPostgresService) -> None:
        worker_db = embedded_postgres_service.clone_template_database("worker_test_db")
        try:
            assert worker_db == "worker_test_db"
        finally:
            embedded_postgres_service.drop_database_force(worker_db)

Template Database Acceleration
------------------------------

Under parallel test execution with ``pytest-xdist``, creating fresh database schemas on every worker adds seconds of overhead. ``EmbeddedPostgresService`` supports copy-on-write template database cloning in ~10–15 milliseconds:

.. code-block:: python

    import pytest
    from pytest_databases.embedded.postgres import EmbeddedPostgresService
    from pytest_databases.types import XdistIsolationLevel

    pytest_plugins = ["pytest_databases.embedded.postgres"]


    @pytest.fixture(scope="session")
    def xdist_embedded_postgres_isolation_level() -> XdistIsolationLevel:
        return "template"


    @pytest.fixture(scope="session")
    def embedded_postgres_template_name() -> str:
        return "app_test_template"


    @pytest.fixture(scope="session")
    def embedded_postgres_template_setup() -> callable:
        def setup(service: EmbeddedPostgresService) -> None:
            # Run schema migrations or seeding once across the entire test session
            service.exec_psql(
                "CREATE TABLE users (id serial PRIMARY KEY, username text NOT NULL);"
            )

        return setup


    def test_worker_database(embedded_postgres_service: EmbeddedPostgresService) -> None:
        # Every worker receives a pre-migrated worker database cloned from the template
        code, output = embedded_postgres_service.exec_psql(
            "SELECT count(*) FROM users;", tuples_only=True
        )
        assert code == 0
        assert output.strip() == b"0"

Available Fixtures
------------------

.. list-table::
   :header-rows: 1
   :widths: 35 20 45

   * - Fixture Name
     - Type
     - Description
   * - ``embedded_postgres_service``
     - ``EmbeddedPostgresService``
     - Session-scoped embedded PostgreSQL instance with multi-worker isolation.
   * - ``embedded_postgres_user``
     - ``str``
     - Database superuser name (defaults to ``"postgres"``).
   * - ``embedded_postgres_password``
     - ``str``
     - Database superuser password (defaults to ``""``).
   * - ``embedded_postgres_database``
     - ``str``
     - Initial database name (defaults to ``"postgres"``).
   * - ``embedded_postgres_port``
     - ``int``
     - Port to bind (``0`` for dynamic ephemeral port allocation).
   * - ``xdist_embedded_postgres_isolation_level``
     - ``XdistIsolationLevel``
     - Multi-worker isolation strategy (``"template"``, ``"database"``, or ``"server"``).
   * - ``embedded_postgres_template_name``
     - ``str``
     - Name of the shared template database.
   * - ``embedded_postgres_template_setup``
     - ``Callable``
     - Optional hook to provision the template database once per test session.
   * - ``embedded_postgres_template_lock_dir``
     - ``Path``
     - Lock directory for cross-worker template synchronization.
