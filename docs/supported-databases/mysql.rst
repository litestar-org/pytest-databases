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
        exit_code, output = mysql_service.exec_sql("SELECT DATABASE()")
        assert exit_code == 0
        assert output.strip().decode() == mysql_service.db

MySQL containers start with ``--performance-schema=ON`` by default and grant global privileges to ``mysql_user`` (or
use ``root`` directly when ``mysql_user`` is ``"root"``). Under ``pytest-xdist`` with the default ``"database"``
isolation level, workers share one container per version and connect to ``<mysql_database>_<worker>``. Custom
fixtures calling :func:`~pytest_databases.docker.mysql.provide_mysql_service` can pass extra ``mysqld`` ``command``
flags, ``env`` variables, ``host_port``, and one-shot ``init_sql`` statements or ``.sql`` files.

Available Fixtures
------------------

* ``mysql_service``: A fixture that provides a MySQL service (8.4 LTS).
* ``mysql_user``: The application user configured in the container (default: ``"app"``, env ``MYSQL_USER``).
* ``mysql_password``: The application user password configured in the container (default: ``"super-secret"``, env ``MYSQL_PASSWORD``).
* ``mysql_root_password``: The root password configured in the container (default: ``"super-secret"``, env ``MYSQL_ROOT_PASSWORD``).
* ``mysql_database``: The base database configured in the container (default: ``"db"``, env ``MYSQL_DATABASE``; ``<mysql_database>_<worker>`` under ``pytest-xdist`` ``"database"`` isolation).
* ``mysql_port``: Optional pinned host port for MySQL containers (default: ``None``, env ``MYSQL_PORT``).
* ``mysql_platform``: Container platform for MySQL 5.6 and 5.7 (default: ``"linux/x86_64"``).
* ``xdist_mysql_isolation_level``: Worker isolation mode: ``"database"`` (default) or ``"server"``.

The following version-specific fixtures are also available:

* ``mysql_56_service``: MySQL 5.6
* ``mysql_57_service``: MySQL 5.7
* ``mysql_8_service``: MySQL 8.0
* ``mysql_84_service``: MySQL 8.4 LTS
* ``mysql_96_service``: MySQL 9.6 Innovation
* ``mysql_97_service``: MySQL 9.7 Innovation

Service API
-----------

.. automodule:: pytest_databases.docker.mysql
   :members:
   :undoc-members:
   :show-inheritance:
