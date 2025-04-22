\
.. _db_sqlserver:

SQL Server
==========

Integration with Microsoft SQL Server.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mssql]

Docker Image
------------

`Microsoft SQL Server Docker Image <https://hub.docker.com/_/microsoft-mssql-server>`_

Configuration
-------------

* ``MSSQL_IMAGE``: Docker image to use for SQL Server (default: "mcr.microsoft.com/mssql/server:2022-latest")
* ``XDIST_MSSQL_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``MSSQL_USER``: Username for SQL Server (default: "sa")
* ``MSSQL_PASSWORD``: Password for SQL Server (default: "Super-secret1")
* ``MSSQL_DATABASE``: Database name for SQL Server (default: "pytest_databases")

API
---

.. automodule:: pytest_databases.docker.mssql
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
