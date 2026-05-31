CockroachDB
===========

Integration with `CockroachDB <https://www.cockroachlabs.com/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[cockroachdb]

The ``cockroachdb`` extra is an empty compatibility group. ``pytest-databases``
no longer bundles a CockroachDB Python client; install your preferred client
(``psycopg``, ``sqlalchemy``, etc.) alongside it.

Usage Example
-------------

.. code-block:: python

    import pytest
    import psycopg
    from pytest_databases.docker.cockroachdb import CockroachDBService

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    @pytest.fixture(scope="session")
    def cockroach_uri(cockroachdb_service: CockroachDBService) -> str:
        return (
            f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}"
            f"/{cockroachdb_service.database}?sslmode=disable"
        )

    def test(cockroach_uri: str) -> None:
        with psycopg.connect(cockroach_uri) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

Available Fixtures
------------------

* ``cockroachdb_image``: The Docker image to use for CockroachDB.
* ``cockroachdb_service``: A fixture that provides a CockroachDB service.

Service API
-----------

.. automodule:: pytest_databases.docker.cockroachdb
   :members:
   :undoc-members:
   :show-inheritance:
