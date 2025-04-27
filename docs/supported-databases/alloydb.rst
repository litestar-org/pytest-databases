AlloyDB Omni
============

Integration with `AlloyDB Omni <https://cloud.google.com/alloydb/omni?hl=en>`_


Installation
------------

.. code-block:: bash

   pip install pytest-databases[postgres]

Usage Example
-------------

.. code-block:: python

    import pytest
    import psycopg

    pytest_plugins = ["pytest_databases.docker.alloydb_omni"]

    def test(alloydb_omni_service: AlloyDBService) -> None:
        with psycopg.connect(
            f"postgresql://{alloydb_omni_service.user}:{alloydb_omni_service.password}@{alloydb_omni_service.host}:{alloydb_omni_service.port}/{alloydb_omni_service.database}"
        ) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

   def test(alloydb_omni_connection: psycopg.Connection) -> None:
        alloydb_omni_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = alloydb_omni_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1

Available Fixtures
------------------

* ``alloydb_omni_image``: The Docker image to use for AlloyDB Omni.
* ``alloydb_omni_service``: A fixture that provides a AlloyDB Omni service.
* ``alloydb_omni_connection``: A fixture that provides a AlloyDB Omni connection.

Service API
-----------

.. automodule:: pytest_databases.docker.alloydb_omni
   :members:
   :undoc-members:
   :show-inheritance:
