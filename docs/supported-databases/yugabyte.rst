Yugabyte
========

Integration with `Yugabyte DB <https://www.yugabyte.com/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[yugabyte]

The fixture provides a running Yugabyte service and validates availability with Yugabyte's bundled tools. Use the
service attributes with the PostgreSQL-compatible client, ORM, or application configuration you normally use.

Usage Example
-------------

.. code-block:: python

    import pytest
    import psycopg
    from pytest_databases.docker.yugabyte import YugabyteService

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def yugabyte_uri(yugabyte_service: YugabyteService) -> str:
        return (
            f"postgresql://{yugabyte_service.user}:{yugabyte_service.password}"
            f"@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?sslmode=disable"
        )

    def test_yugabyte_service(yugabyte_uri: str) -> None:
        with psycopg.connect(yugabyte_uri) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1

Available Fixtures
------------------

* ``yugabyte_image``: The Docker image to use for Yugabyte DB.
* ``yugabyte_user``: The Yugabyte user exposed on ``yugabyte_service``.
* ``yugabyte_password``: The Yugabyte password exposed on ``yugabyte_service``.
* ``yugabyte_service``: A fixture that provides a Yugabyte DB service.

Service API
-----------

.. automodule:: pytest_databases.docker.yugabyte
   :members:
   :undoc-members:
   :show-inheritance:
