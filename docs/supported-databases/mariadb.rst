MariaDB
=======

Integration with `MariaDB <https://mariadb.org>`_, a community-developed, commercially supported fork of the MySQL relational database management system.

This integration uses the official `MariaDB Python Connector <https://mariadb.com/docs/clients/mariadb-connectors/connector-python/>`_ to interact with MariaDB.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mariadb]


Usage Example
-------------

.. code-block:: python

    import pytest
    import mariadb
    from pytest_databases.docker.mariadb import MariaDBService

    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def test(mariadb_service: MariaDBService) -> None:
        with mariadb.connect(
            host=mariadb_service.host,
            port=mariadb_service.port,
            user=mariadb_service.user,
            database=mariadb_service.db,
            password=mariadb_service.password,
        ) as conn, conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            assert resp is not None and resp[0] == 1

    def test(mariadb_connection: mariadb.Connection) -> None:
        with mariadb_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert result is not None and result[0][0] == 1

Available Fixtures
------------------

* ``mariadb_service``: A fixture that provides a MariaDB service.
* ``mariadb_connection``: A fixture that provides a MariaDB connection.

The following version-specific fixtures are also available:

* ``mariadb_113_service``: A fixture that provides a MariaDB 11.3 service.
* ``mariadb_113_connection``: A fixture that provides a MariaDB 11.3 connection.


Service API
-----------

.. automodule:: pytest_databases.docker.mariadb
   :members:
   :undoc-members:
   :show-inheritance:
