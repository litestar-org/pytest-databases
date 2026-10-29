IBM Db2
=======

Integration with `IBM Db2 Community Edition <https://www.ibm.com/products/db2-database>`_
using the official ``icr.io/db2_community/db2:latest`` container image. The
fixture is clientless and uses the in-container ``db2`` CLI for readiness
probing and worker database provisioning without requiring ``ibm-db`` to be
installed in the base environment.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``ibm-db`` or your preferred Db2 driver in your project if your tests
open host-side connections.

Docker Image & Runtime Capabilities
-----------------------------------

The default image is ``icr.io/db2_community/db2:latest`` on container port
``50000``. Because the Db2 engine initializes shared memory segments and kernel
IPC resources during container startup, ``db2_service`` automatically starts the
container with ``privileged=True`` and ``ipc_mode="host"`` and disables sample
database creation (``SAMPLEDB="false"``, ``AUTOCONFIG="false"``) for faster startup.

.. note::

   Db2 database names are restricted to a maximum of 8 characters. Both
   ``db2_dbname`` (default ``pytestdb``) and xdist worker database names
   (``ptdb_0``, ``ptdb_1``, ...) enforce this 8-character limit.

Usage Example
-------------

.. code-block:: python

   from pytest_databases.docker.db2 import Db2Service

   pytest_plugins = ["pytest_databases.docker.db2"]


   def test_db2_query(db2_service: Db2Service) -> None:
       output = db2_service.exec_sql("SELECT 1 FROM SYSIBM.SYSDUMMY1")
       assert "1" in output
       assert db2_service.connection_config["database"] == db2_service.db_name
       assert "PROTOCOL=TCPIP;" in db2_service.dsn

Available Fixtures
------------------

* ``db2_image``: Container image (default: ``icr.io/db2_community/db2:latest``).
* ``db2_dbname``: 8-character-compliant database name (default: ``pytestdb``).
* ``db2_username``: Instance owner username (default: ``db2inst1``).
* ``db2_password``: Instance owner password (default: ``pytest_db2_pwd``).
* ``db2_startup_timeout``: Startup timeout in seconds (default: ``600``).
* ``db2_host`` and ``db2_port``: Mapped host and TCP port.
* ``xdist_db2_isolation_level``: ``"database"`` (per-worker ``ptdb_<n>`` database)
  or ``"server"`` (per-worker container).
* ``db2_service``: :class:`~pytest_databases.docker.db2.Db2Service` instance.

Service API
-----------

.. automodule:: pytest_databases.docker.db2
   :members:
   :undoc-members:
   :show-inheritance:
