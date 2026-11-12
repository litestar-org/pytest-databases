CockroachDB
===========

Integration with `CockroachDB <https://www.cockroachlabs.com/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases

The fixture validates the container without a Python client. Install your preferred client (``psycopg``,
``sqlalchemy``, etc.) alongside it. The ``cockroachdb`` extra no longer installs ``psycopg``.

Usage Example
-------------

.. code-block:: python

    import psycopg
    from pytest_databases.docker.cockroachdb import CockroachDBService

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]


    def test_cockroachdb(cockroachdb_service: CockroachDBService) -> None:
        exit_code, output = cockroachdb_service.exec_sql("SELECT 1")
        assert exit_code == 0
        assert isinstance(output, bytes)
        assert cockroachdb_service.connection_config["database"] == cockroachdb_service.database
        with psycopg.connect(cockroachdb_service.dsn) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

``CockroachDBService`` exposes ``user`` (default ``"root"``), ``dsn`` (``postgresql://root@host:port/database?sslmode=disable``),
``connection_config`` (``host``, ``port``, ``user``, ``database``, plus ``driver_opts``), and
``exec_sql(sql, *, database=None) -> tuple[int, bytes]``, delegating to public
:func:`~pytest_databases.docker.cockroachdb.exec_cockroach_sql`.

Available Fixtures
------------------

* ``cockroachdb_image``: The Docker image to use for CockroachDB.
* ``cockroachdb_service``: A fixture that provides a :class:`~pytest_databases.docker.cockroachdb.CockroachDBService` instance.

Service API
-----------

.. automodule:: pytest_databases.docker.cockroachdb
   :members:
   :undoc-members:
   :show-inheritance:
