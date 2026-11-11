SQL Server
==========

Integration with `Microsoft SQL Server <https://www.microsoft.com/en-us/sql-server/>`_ using the `Microsoft SQL Server Docker Image <https://hub.docker.com/_/microsoft-mssql-server>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases

The fixture provides a running SQL Server service and validates
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
        exit_code, output = mssql_service.exec_sql("SET NOCOUNT ON; SELECT DB_NAME()")
        assert exit_code == 0
        assert output.strip().decode() == mssql_service.database

:meth:`~pytest_databases.docker.mssql.MSSQLService.exec_sql` and :func:`~pytest_databases.docker.mssql.exec_sqlcmd`
supply credentials via ``SQLCMDPASSWORD`` rather than process arguments, and automatically stage multi-batch scripts
containing standalone ``GO`` separators or host ``sql_file`` paths into the container before running ``sqlcmd -i``.
Custom fixtures calling :func:`~pytest_databases.docker.mssql.provide_mssql_service` can pass ``env`` overrides (for
example ``{"MSSQL_AGENT_ENABLED": "true"}`` or custom ``MSSQL_COLLATION``), ``host_port``, ``mem_limit``,
``shm_size``, and one-shot ``init_sql`` statements or ``.sql`` files (such as enabling Query Store).

Available Fixtures
------------------

* ``mssql_image``: The Docker image to use for SQL Server (defaults to ``mssql_2022_image``).
* ``mssql_2022_image`` and ``mssql_2025_image``: Version-specific SQL Server 2022 and 2025 images.
* ``mssql_user``: The SQL Server user exposed on ``mssql_service`` (default: ``"sa"``, env ``MSSQL_USER``).
* ``mssql_password``: The SQL Server password exposed on ``mssql_service`` (default: ``"Super-secret1"``, env ``MSSQL_PASSWORD``).
* ``mssql_database``: The base database created for ``mssql_service`` (default: ``"pytest_databases"``, env ``MSSQL_DATABASE``; ``<mssql_database>_<worker>`` under ``pytest-xdist`` ``"database"`` isolation).
* ``mssql_port``: Optional pinned host port for SQL Server containers (default: ``None``, env ``MSSQL_PORT``).
* ``xdist_mssql_isolation_level``: Worker isolation mode: ``"database"`` (default) or ``"server"``.
* ``mssql_service``: A fixture that provides a SQL Server service. With the default ``mssql_image`` it shares the
  ``mssql_2022_service`` container; when ``mssql_image`` is overridden it starts its own container.
* ``mssql_2022_service`` and ``mssql_2025_service``: Version-specific SQL Server 2022 and 2025 services.

Service API
-----------

.. automodule:: pytest_databases.docker.mssql
   :members:
   :undoc-members:
   :show-inheritance:
