Yugabyte
========

Integration with `Yugabyte DB <https://www.yugabyte.com/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[yugabyte]

Usage Example
-------------

.. code-block:: python

    import pytest
    import psycopg
    from pytest_databases.docker.yugabyte import YugabyteService

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def yugabyte_uri(yugabyte_service: YugabyteService) -> str:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_service.driver_opts.items())
        return f"postgresql://yugabyte:yugabyte@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"

    def test_yugabyte_service(yugabyte_uri: str) -> None:
        with psycopg.connect(yugabyte_uri) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

    def test_yugabyte_connection(yugabyte_connection: psycopg.Connection) -> None:
        yugabyte_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = yugabyte_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1

Available Fixtures
------------------

* ``yugabyte_image``: The Docker image to use for Yugabyte DB.
* ``yugabyte_service``: A fixture that provides a Yugabyte DB service.
* ``yugabyte_connection``: A fixture that provides a Yugabyte DB connection.
* ``yugabyte_driver_opts``: A fixture that provides driver options for Yugabyte DB.

Service API
-----------

.. automodule:: pytest_databases.docker.yugabyte
   :members:
   :undoc-members:
   :show-inheritance:
