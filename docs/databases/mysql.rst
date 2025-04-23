MySQL
=====

Integration with `MySQL <https://www.mysql.com/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mysql]

Usage Example
-------------

.. code-block:: python

    import pytest
    import mysql.connector
    from pytest_databases.docker.mysql import MySQLService

    pytest_plugins = ["pytest_databases.docker.mysql"]

    def test(mysql_service: MySQLService) -> None:
        with mysql.connector.connect(
            host=mysql_service.host,
            port=mysql_service.port,
            user=mysql_service.user,
            database=mysql_service.db,
            password=mysql_service.password,
        ) as conn, conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            assert resp is not None and resp[0] == 1

    def test(mysql_connection: mysql.connector.MySQLConnection) -> None:
        with mysql_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert result is not None and result[0][0] == 1

Available Fixtures
------------------

* ``mysql_service``: A fixture that provides a MySQL service (latest version).
* ``mysql_connection``: A fixture that provides a MySQL connection.

The following version-specific fixtures are also available:

* ``mysql_56_service``, ``mysql_56_connection``: MySQL 5.6
* ``mysql_57_service``, ``mysql_57_connection``: MySQL 5.7
* ``mysql_8_service``, ``mysql_8_connection``: MySQL 8.x

Service API
-----------

.. automodule:: pytest_databases.docker.mysql
   :members:
   :undoc-members:
   :show-inheritance:
