SAP SQL Anywhere
=================

Integration with `SAP SQL Anywhere <https://www.sap.com/products/technology-platform/sql-anywhere.html>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``sqlanydb`` in your project if your tests connect from the host.
The service fixtures validate container readiness using host TCP socket probing on port 2638 and in-container ``dbisql`` CLI tools without requiring driver packages in the base installation.

Usage Example
-------------

.. code-block:: python

   import sqlanydb
   from pytest_databases.docker.sqlanywhere import SQLAnywhereService

   pytest_plugins = ["pytest_databases.docker.sqlanywhere"]


   def test_sqlanywhere_connection(sqlanywhere_service: SQLAnywhereService) -> None:
       conn = sqlanydb.connect(
           uid=sqlanywhere_service.user,
           pwd=sqlanywhere_service.password,
           eng=sqlanywhere_service.server_name,
           dbn=sqlanywhere_service.database,
           host=f"{sqlanywhere_service.host}:{sqlanywhere_service.port}",
       )
       with conn.cursor() as cur:
           cur.execute("SELECT 1")
           res = cur.fetchone()[0]
           assert res == 1

Available Fixtures
------------------

* ``sqlanywhere_image``: Docker image tag for SAP SQL Anywhere (default: ``jaschweder/sybase:latest``).
* ``sqlanywhere_user``: Login user for the SQL Anywhere instance (default: ``dba``).
* ``sqlanywhere_password``: Login password for the SQL Anywhere instance (default: ``sql``).
* ``sqlanywhere_database``: Initial database to connect to (default: ``demo``).
* ``sqlanywhere_server``: Database server / engine name (default: ``demo``).
* ``sqlanywhere_startup_timeout``: Timeout in seconds for container startup (default: ``60``).
* ``xdist_sqlanywhere_isolation_level``: Worker isolation mode (default: ``server``).
* ``sqlanywhere_service``: Provides a running SAP SQL Anywhere service container.
* ``sqlanywhere_client_libs``: Extracts native SAP SQL Anywhere client libraries (``lib64`` and ``res``) from the container, preloads dependent shared libraries, and exports ``SQLANY16`` and ``SQLANY_API_DLL`` for zero-host-setup ``sqlanydb`` testing.

Service API
-----------

.. automodule:: pytest_databases.docker.sqlanywhere
   :members:
   :undoc-members:
   :show-inheritance:
