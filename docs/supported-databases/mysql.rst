MySQL
=====

Integration with `MySQL <https://www.mysql.com/>`_

Installation
------------

The fixture provides a running MySQL service and validates availability with the container's bundled tools. Use the
service attributes with the MySQL client, ORM, or application configuration you normally use.

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

Available Fixtures
------------------

* ``mysql_service``: A fixture that provides a MySQL service (8.4 LTS).
* ``mysql_user``: The application user configured in the container.
* ``mysql_password``: The application user password configured in the container.
* ``mysql_root_password``: The root password configured in the container.
* ``mysql_database``: The initial database configured in the container.

The following version-specific fixtures are also available:

* ``mysql_56_service``: MySQL 5.6
* ``mysql_57_service``: MySQL 5.7
* ``mysql_8_service``: MySQL 8.0
* ``mysql_84_service``: MySQL 8.4 LTS
* ``mysql_96_service``: MySQL 9.6 Innovation

Service API
-----------

.. automodule:: pytest_databases.docker.mysql
   :members:
   :undoc-members:
   :show-inheritance:
