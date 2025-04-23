CockroachDB
===========

Integration with `CockroachDB <https://www.cockroachlabs.com/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[cockroachdb]

Usage Example
-------------

.. code-block:: python

    import pytest
    import psycopg
    from pytest_databases.docker.cockroachdb import CockroachDBService

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    @pytest.fixture(scope="session")
    def cockroach_uri(cockroachdb_service: CockroachDBService) -> str:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
        return f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"

    def test(cockroach_uri: str) -> None:
        with psycopg.connect(cockroach_uri) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

    def test(cockroachdb_connection: psycopg.Connection) -> None:
        cockroachdb_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = cockroachdb_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1

Available Fixtures
------------------

* ``cockroachdb_image``: The Docker image to use for CockroachDB.
* ``cockroachdb_service``: A fixture that provides a CockroachDB service.
* ``cockroachdb_connection``: A fixture that provides a CockroachDB connection.
* ``cockroachdb_driver_opts``: A fixture that provides driver options for CockroachDB.

Service API
-----------

.. automodule:: pytest_databases.docker.cockroachdb
   :members:
   :undoc-members:
   :show-inheritance:
