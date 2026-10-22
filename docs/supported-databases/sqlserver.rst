SQL Server
==========

Integration with `Microsoft SQL Server <https://www.microsoft.com/en-us/sql-server/>`_ using the `Microsoft SQL Server Docker Image <https://hub.docker.com/_/microsoft-mssql-server>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mssql]

The ``mssql`` extra is kept as a compatibility group. The fixture provides a running SQL Server service and validates
availability with SQL Server's bundled tools. Install the SQL Server client library that your application already uses.

Usage Example
-------------

.. code-block:: python

    import pyodbc
    from pytest_databases.docker.mssql import MSSQLService

    pytest_plugins = ["pytest_databases.docker.mssql"]

    def test_sql_server_service(mssql_service: MSSQLService) -> None:
        with pyodbc.connect(mssql_service.connection_string) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 AS is_available")
            row = cursor.fetchone()
            assert row is not None and row[0] == 1

Available Fixtures
------------------

* ``mssql_image``: The Docker image to use for SQL Server (defaults to ``mssql_2022_image``).
* ``mssql_2022_image`` and ``mssql_2025_image``: Version-specific SQL Server 2022 and 2025 images.
* ``mssql_user``: The SQL Server user exposed on ``mssql_service``.
* ``mssql_password``: The SQL Server password exposed on ``mssql_service``.
* ``mssql_database``: The database created for ``mssql_service``.
* ``mssql_service``: A fixture that provides a SQL Server service (aliases ``mssql_2022_service``).
* ``mssql_2022_service`` and ``mssql_2025_service``: Version-specific SQL Server 2022 and 2025 services.

Service API
-----------

.. automodule:: pytest_databases.docker.mssql
   :members:
   :undoc-members:
   :show-inheritance:
