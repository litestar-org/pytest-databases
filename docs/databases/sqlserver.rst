SQL Server
==========

Integration with `Microsoft SQL Server <https://www.microsoft.com/en-us/sql-server/>`_ using the `Microsoft SQL Server Docker Image <https://hub.docker.com/_/microsoft-mssql-server>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mssql]

Usage Example
-------------

.. code-block:: python

    import pytest
    import pymssql
    from pytest_databases.docker.mssql import MSSQLService

    pytest_plugins = ["pytest_databases.docker.mssql"]

    def test(mssql_service: MSSQLService) -> None:
        conn = pymssql.connect(
            host=mssql_service.host,
            port=str(mssql_service.port),
            database=mssql_service.database,
            user=mssql_service.user,
            password=mssql_service.password,
            timeout=2,
        )
        with conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            assert resp is not None and resp[0] == 1

    def test(mssql_connection: pymssql.Connection) -> None:
        with mssql_connection.cursor() as cursor:
            cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert result is not None and result[0][0] == 1
            cursor.execute("drop view simple_table")

Available Fixtures
------------------

* ``mssql_image``: The Docker image to use for SQL Server.
* ``mssql_service``: A fixture that provides a SQL Server service.
* ``mssql_connection``: A fixture that provides a SQL Server connection.

Service API
-----------

.. automodule:: pytest_databases.docker.mssql
   :members:
   :undoc-members:
   :show-inheritance:
