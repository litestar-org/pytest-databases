Dolt
====

Integration with `Dolt <https://www.dolthub.com/>`_

Dolt is a MySQL-compatible database that provides Git-like versioning for your data.

Installation
------------

The fixture provides a running Dolt SQL service and validates availability with the container's bundled tools. Since
Dolt is MySQL-compatible, use the service attributes with the MySQL client, ORM, or application configuration you
normally use.

Usage Example
-------------

.. code-block:: python

    import pytest
    import mysql.connector
    from pytest_databases.docker.dolt import DoltService

    pytest_plugins = ["pytest_databases.docker.dolt"]

    def test(dolt_service: DoltService) -> None:
        with mysql.connector.connect(
            host=dolt_service.host,
            port=dolt_service.port,
            user=dolt_service.user,
            database=dolt_service.db,
            password=dolt_service.password,
        ) as conn, conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            assert resp is not None and resp[0] == 1

Available Fixtures
------------------

* ``dolt_service``: A fixture that provides a Dolt service (latest).
* ``dolt_user``: The application user configured in the container.
* ``dolt_password``: The application user password configured in the container.
* ``dolt_root_password``: The root password configured in the container.
* ``dolt_database``: The initial database configured in the container.

Isolation Level
---------------

By default, the ``dolt_service`` fixture uses ``database`` isolation, where each worker gets its own database on a shared server. You can change this to ``server`` isolation by overriding the ``xdist_dolt_isolation_level`` fixture.

.. code-block:: python

    @pytest.fixture(scope="session")
    def xdist_dolt_isolation_level():
        return "server"

Service API
-----------

.. automodule:: pytest_databases.docker.dolt
   :members:
   :undoc-members:
   :show-inheritance:
