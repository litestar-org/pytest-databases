GizmoSQL
========

Integration with `GizmoSQL <https://github.com/gizmodata/gizmosql>`_, a high-performance SQL server built on Apache Arrow Flight SQL with DuckDB/SQLite backends.

.. note::

   GizmoSQL always runs with TLS enabled using auto-generated self-signed certificates.
   When you connect from your own client code, configure TLS to skip certificate verification.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[gizmosql]

Usage Example
-------------

The plugin validates container readiness via ``gizmosql_client`` inside the container without requiring ``adbc-driver-flightsql`` at startup. Connect using the ``uri`` and ``connection_kwargs`` properties on ``GizmoSQLService``. ``gizmosql_service`` uses DuckDB by default:

.. code-block:: python

    from adbc_driver_flightsql import dbapi as flightsql
    from pytest_databases.docker.gizmosql import GizmoSQLService

    pytest_plugins = ["pytest_databases.docker.gizmosql"]


    def test(gizmosql_service: GizmoSQLService) -> None:
        with flightsql.connect(
            uri=gizmosql_service.uri,
            db_kwargs=gizmosql_service.connection_kwargs,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE test_table (id INTEGER, name VARCHAR);
                    INSERT INTO test_table VALUES (1, 'test');
                """)

            with conn.cursor() as cur:
                cur.execute("SELECT * FROM test_table")
                result = cur.fetchone()
                assert result is not None
                assert result[0] == 1

.. note::

   Due to Flight SQL semantics, DDL and DML statements should be combined in a single
   ``execute()`` call for immediate visibility across cursor operations.

Available Fixtures
------------------

* ``gizmosql_image``: The Docker image to use for GizmoSQL (default: ``gizmodata/gizmosql:latest``).
* ``gizmosql_username``: The username for authentication.
* ``gizmosql_password``: The password for authentication.
* ``gizmosql_duckdb_service``: A GizmoSQL service explicitly configured with the DuckDB backend.
* ``gizmosql_sqlite_service``: A GizmoSQL service explicitly configured with the SQLite backend.
* ``gizmosql_service``: The backward-compatible default, which returns ``gizmosql_duckdb_service``.
* ``xdist_gizmosql_isolation_level``: Xdist isolation level (default: ``database``).

Both backend-specific fixtures can be requested in the same test session. They use distinct
containers and share the image, username, password, TLS, readiness, and teardown configuration:

.. code-block:: python

    from pytest_databases.docker.gizmosql import GizmoSQLService


    def test_backends(
        gizmosql_duckdb_service: GizmoSQLService,
        gizmosql_sqlite_service: GizmoSQLService,
    ) -> None:
        assert gizmosql_duckdb_service.uri != gizmosql_sqlite_service.uri

Parallel Testing (xdist)
------------------------

GizmoSQL assigns each ``pytest-xdist`` worker its own container per backend because embedded DuckDB and SQLite instances do not provide independent server databases.

.. code-block:: python

    @pytest.fixture(scope="session")
    def xdist_gizmosql_isolation_level():
        return "server"

Service API
-----------

.. automodule:: pytest_databases.docker.gizmosql
   :members:
   :undoc-members:
   :show-inheritance:
