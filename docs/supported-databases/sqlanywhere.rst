SAP SQL Anywhere
================

Integration with `SAP SQL Anywhere <https://www.sap.com/products/technology-platform/sql-anywhere.html>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``sqlanydb`` if your tests connect from the host. The fixture checks readiness with a TCP probe and the
``dbisqlc`` client inside the container, so no driver is needed to start it. ``sqlanydb`` also needs SAP's native
client libraries; the ``sqlanywhere_client_libs`` fixture copies them out of the running container.

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

Parallel Execution
------------------

Only ``server`` isolation is supported, and it is the default: every ``pytest-xdist`` worker starts its own container
(``sqlanywhere_<worker>``). The default image serves one database file and cannot create a database per worker, so
``xdist_sqlanywhere_isolation_level`` returning ``database`` raises ``ValueError``.

The default image always serves the ``demo`` database on the ``demo`` server as ``dba`` / ``sql``. Overriding
``sqlanywhere_user``, ``sqlanywhere_password``, ``sqlanywhere_database`` or ``sqlanywhere_server`` only changes how the
fixture connects, so use an image that matches the new values.

Available Fixtures
------------------

* ``sqlanywhere_image``: Docker image tag for SAP SQL Anywhere (default: ``jaschweder/sybase:latest``, env
  ``SQLANYWHERE_IMAGE``).
* ``sqlanywhere_user``: Login user for the SQL Anywhere instance (default: ``dba``, env ``SQLANYWHERE_USER``).
* ``sqlanywhere_password``: Login password for the SQL Anywhere instance (default: ``sql``, env
  ``SQLANYWHERE_PASSWORD``).
* ``sqlanywhere_database``: Database to connect to (default: ``demo``, env ``SQLANYWHERE_DATABASE``).
* ``sqlanywhere_server``: Database server / engine name (default: ``demo``, env ``SQLANYWHERE_SERVER``).
* ``sqlanywhere_startup_timeout``: Timeout in seconds for container startup (default: ``60``, env
  ``SQLANYWHERE_STARTUP_TIMEOUT``).
* ``xdist_sqlanywhere_isolation_level``: Worker isolation mode (default and only supported value: ``server``).
* ``sqlanywhere_service``: Provides a running SAP SQL Anywhere service container.
* ``sqlanywhere_client_libs``: Copies the native client libraries (``lib64`` and ``res``) out of the container,
  preloads them, and sets ``SQLANY16`` and ``SQLANY_API_DLL`` for the rest of the session. The previous values are
  restored when the session ends.

Service API
-----------

.. automodule:: pytest_databases.docker.sqlanywhere
   :members:
   :undoc-members:
   :show-inheritance:
