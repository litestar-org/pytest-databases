IBM Db2
=======

Integration with `IBM Db2 Community Edition <https://www.ibm.com/products/db2-database>`_
using the official ``icr.io/db2_community/db2:12.1.5.0`` container image. The
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

The default image is ``icr.io/db2_community/db2:12.1.5.0`` on container port
``50000``. Db2 adjusts kernel IPC parameters inside its own namespace during
startup, so ``db2_service`` starts the container with ``privileged=True`` (as in
IBM's documented ``docker run``). Each container keeps its own IPC namespace, so
several Db2 containers on one host do not share IPC keys. Sample database
creation is disabled (``SAMPLEDB="false"``, ``AUTOCONFIG="false"``) for faster
startup.

Storage with 4096-byte logical sectors (for example an overlay2 Docker root on a
4Kn or dm-crypt device) makes Db2's default direct I/O fail with ``SQL0293N``, and
the initial database is never created. ``db2_service`` therefore sets the Db2
registry variables ``DB2_4K_DEVICE_SUPPORT=ON`` and ``DB2_DIRECT_IO=NO`` by
default: the image setup script is patched to set them before its first
``db2start``, and if the initial database is still missing after setup
(``SQL1013N``) the variables are applied, the instance is restarted, and the
database is created once. Both settings also work on 512-byte storage. Override
the ``db2_4k_device_support`` fixture to return ``False`` (or set
``DB2_4K_DEVICE_SUPPORT=off``) to start the image unchanged.

``Db2Service.exec_sql`` runs a statement through the in-container ``db2`` command
line processor. Exit code 1 (no rows, ``SQL0100W``) and 2 (warnings) count as
success and the warning text is returned with the output; error codes of 4 and
above raise ``RuntimeError``.

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

* ``db2_image``: Container image (default: ``icr.io/db2_community/db2:12.1.5.0``, env ``DB2_IMAGE``).
* ``db2_dbname``: 8-character-compliant database name (default: ``pytestdb``).
* ``db2_username``: Instance owner username (default: ``db2inst1``).
* ``db2_password``: Instance owner password (default: ``pytest_db2_pwd``).
* ``db2_startup_timeout``: Startup timeout in seconds (default: ``600``).
* ``db2_4k_device_support``: Apply ``DB2_4K_DEVICE_SUPPORT=ON`` and ``DB2_DIRECT_IO=NO``
  (default: ``True``, env ``DB2_4K_DEVICE_SUPPORT``).
* ``xdist_db2_isolation_level``: ``"database"`` (per-worker ``ptdb_<n>`` database)
  or ``"server"`` (one transient ``db2_<n>`` container per xdist worker).
* ``db2_service``: :class:`~pytest_databases.docker.db2.Db2Service` instance.

Service API
-----------

.. automodule:: pytest_databases.docker.db2
   :members:
   :undoc-members:
   :show-inheritance:
