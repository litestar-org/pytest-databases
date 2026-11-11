MariaDB
=======

Integration with `MariaDB <https://mariadb.org>`_, a community-developed, commercially supported fork of the MySQL relational database management system.

Installation
------------

The fixture provides a running MariaDB service and validates availability with the container's bundled tools. Use the
service attributes with the MariaDB client, ORM, or application configuration you normally use.

Usage Example
-------------

.. code-block:: python

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
        exit_code, output = mariadb_service.exec_sql("SELECT DATABASE()")
        assert exit_code == 0
        assert output.strip().decode() == mariadb_service.db

MariaDB containers start with ``--performance-schema=ON`` by default and grant global privileges to ``mariadb_user``
(or use ``root`` directly when ``mariadb_user`` is ``"root"``). Under ``pytest-xdist`` with the default ``"database"``
isolation level, workers share one container per version and connect to ``<mariadb_database>_<worker>``. Custom
fixtures calling :func:`~pytest_databases.docker.mariadb.provide_mariadb_service` can pass extra ``mariadbd``
``command`` flags, ``env`` variables, ``host_port``, and one-shot ``init_sql`` statements or ``.sql`` files.

Available Fixtures
------------------

* ``mariadb_service``: A fixture that provides a MariaDB service (11.4 LTS).
* ``mariadb_user``: The application user configured in the container (default: ``"app"``, env ``MARIADB_USER``).
* ``mariadb_password``: The application user password configured in the container (default: ``"super-secret"``, env ``MARIADB_PASSWORD``).
* ``mariadb_root_password``: The root password configured in the container (default: ``"super-secret"``, env ``MARIADB_ROOT_PASSWORD``).
* ``mariadb_database``: The base database configured in the container (default: ``"db"``, env ``MARIADB_DATABASE``; ``<mariadb_database>_<worker>`` under ``pytest-xdist`` ``"database"`` isolation).
* ``mariadb_port``: Optional pinned host port for MariaDB containers (default: ``None``, env ``MARIADB_PORT``).
* ``xdist_mariadb_isolation_level``: Worker isolation mode: ``"database"`` (default) or ``"server"``.

The following version-specific fixtures are also available:

* ``mariadb_113_service``: MariaDB 11.3
* ``mariadb_114_service``: MariaDB 11.4 LTS
* ``mariadb_118_service``: MariaDB 11.8 LTS
* ``mariadb_122_service``: MariaDB 12.2 Rolling
* ``mariadb_123_service``: MariaDB 12.3 Rolling
* ``mariadb_130_service``: MariaDB 13.0 Rolling

Service API
-----------

.. automodule:: pytest_databases.docker.mariadb
   :members:
   :undoc-members:
   :show-inheritance:
