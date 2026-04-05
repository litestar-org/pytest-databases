MySQL
=====

Integration with `MySQL <https://www.mysql.com/>`_

Installation
------------

MySQL support is built-in and does not require any additional Python client libraries for basic service management. However, to connect to the database from your tests, you should install your preferred MySQL client (e.g., `mysql-connector-python`).

Usage Example
-------------

.. code-block:: python

    import pytest
    import mysql.connector
    from pytest_databases.docker.mysql import MySQLService

    pytest_plugins = ["pytest_databases.docker.mysql"]

    def test(mysql_service: MySQLService) -> None:
        # Create your own connection using the service fixture attributes
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

Available Fixtures
------------------

* ``mysql_service``: A fixture that provides a MySQL service (8.4 LTS).

The following version-specific fixtures are also available:

* ``mysql_56_service``: MySQL 5.6
* ``mysql_57_service``: MySQL 5.7
* ``mysql_8_service``: MySQL 8.0
* ``mysql_84_service``: MySQL 8.4 LTS
* ``mysql_96_service``: MySQL 9.6 Innovation

.. note::
   The connection fixtures (e.g., ``mysql_connection``, ``mysql_84_connection``) are deprecated and will be removed in a future release. Users are encouraged to create their own connections as shown in the example above.

Service API
-----------

.. automodule:: pytest_databases.docker.mysql
   :members:
   :undoc-members:
   :show-inheritance:
