MariaDB
=======

Integration with `MariaDB <https://mariadb.org>`_, a community-developed, commercially supported fork of the MySQL relational database management system.

Installation
------------

MariaDB support is built-in and does not require any additional Python client libraries for basic service management. However, to connect to the database from your tests, you should install your preferred MariaDB client (e.g., `mariadb`).

Usage Example
-------------

.. code-block:: python

    import pytest
    import mariadb
    from pytest_databases.docker.mariadb import MariaDBService

    pytest_plugins = ["pytest_databases.docker.mariadb"]

    def test(mariadb_service: MariaDBService) -> None:
        # Create your own connection using the service fixture attributes
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

The following version-specific fixtures are also available:

* ``mariadb_113_service``: MariaDB 11.3
* ``mariadb_114_service``: MariaDB 11.4 LTS
* ``mariadb_122_service``: MariaDB 12.2 Rolling

.. note::
   The connection fixtures (e.g., ``mariadb_connection``, ``mariadb_114_connection``) are deprecated and will be removed in a future release. Users are encouraged to create their own connections as shown in the example above.

Service API
-----------

.. automodule:: pytest_databases.docker.mariadb
   :members:
   :undoc-members:
   :show-inheritance:
