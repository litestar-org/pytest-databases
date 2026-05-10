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

Available Fixtures
------------------

* ``mariadb_service``: A fixture that provides a MariaDB service (11.4 LTS).
* ``mariadb_user``: The application user configured in the container.
* ``mariadb_password``: The application user password configured in the container.
* ``mariadb_root_password``: The root password configured in the container.
* ``mariadb_database``: The initial database configured in the container.

The following version-specific fixtures are also available:

* ``mariadb_113_service``: MariaDB 11.3
* ``mariadb_114_service``: MariaDB 11.4 LTS
* ``mariadb_122_service``: MariaDB 12.2 Rolling

Service API
-----------

.. automodule:: pytest_databases.docker.mariadb
   :members:
   :undoc-members:
   :show-inheritance:
