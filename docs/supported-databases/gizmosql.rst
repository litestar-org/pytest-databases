GizmoSQL
========

Integration with `GizmoSQL <https://github.com/gizmodata/gizmosql>`_, a high-performance SQL server built on Apache Arrow Flight SQL with DuckDB/SQLite backends.

.. note::

   GizmoSQL always runs with TLS enabled using auto-generated self-signed certificates.
   The connection fixtures automatically skip certificate verification for testing purposes.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[gizmosql]

Usage Example
-------------

Using the service fixture:

.. code-block:: python

    import pytest
    from adbc_driver_flightsql import dbapi as flightsql
    from pytest_databases.docker.gizmosql import GizmoSQLService, _make_connection_kwargs

    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    def test(gizmosql_service: GizmoSQLService) -> None:
        db_kwargs = _make_connection_kwargs(
            gizmosql_service.username,
            gizmosql_service.password,
        )
        with flightsql.connect(
            uri=gizmosql_service.uri,
            db_kwargs=db_kwargs,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                assert result is not None and result[0] == 1

Using the connection fixture:

.. code-block:: python

    import pytest

    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    def test(gizmosql_connection) -> None:
        with gizmosql_connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE test_table (id INTEGER, name VARCHAR);
                INSERT INTO test_table VALUES (1, 'test');
            """)

        with gizmosql_connection.cursor() as cur:
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
* ``gizmosql_service``: A fixture that provides a GizmoSQL service container.
* ``gizmosql_connection``: A fixture that provides an ADBC Flight SQL connection.
* ``xdist_gizmosql_isolation_level``: Xdist isolation level (default: ``server``).

Parallel Testing (xdist)
------------------------

GizmoSQL only supports ``server`` isolation level for pytest-xdist parallel testing.
This means each xdist worker gets its own dedicated container. Database-level isolation
is not supported because DuckDB (the default backend) doesn't support multiple databases
per instance.

.. code-block:: python

    @pytest.fixture(scope="session")
    def xdist_gizmosql_isolation_level():
        return "server"  # This is the only supported value

Service API
-----------

.. automodule:: pytest_databases.docker.gizmosql
   :members:
   :undoc-members:
   :show-inheritance:
