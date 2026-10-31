Sybase ASE
==========

Integration with `SAP Sybase Adaptive Server Enterprise (ASE) <https://www.sap.com/products/technology-platform/sybase-ase.html>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``pymssql`` (built with FreeTDS TDS 5.0 support) if your tests connect from the host. The fixture checks
readiness with a TCP probe and the ``isql`` client inside the container, so no driver is needed to start it.

Usage Example
-------------

.. code-block:: python

   import pymssql
   from pytest_databases.docker.sybase import SybaseService

   pytest_plugins = ["pytest_databases.docker.sybase"]


   def test_sybase_connection(sybase_service: SybaseService) -> None:
       conn = pymssql.connect(
           server=sybase_service.host,
           port=sybase_service.port,
           user=sybase_service.user,
           password=sybase_service.password,
           database=sybase_service.database,
           autocommit=True,
       )
       with conn.cursor() as cur:
           cur.execute("SELECT 1")
           res = cur.fetchone()[0]
           assert res == 1

Parallel Execution
------------------

With the default ``database`` isolation, ``pytest-xdist`` workers share one container and each worker gets its own
database: ``<sybase_database>_<worker>``, or ``pytestdb_<worker>`` when ``sybase_database`` is ``master``. The name must
be a valid ASE identifier of at most 30 characters. Each database is created on its own ``<database>_dev`` device
(48 MB) next to the ``master`` device, because the default image's ``master`` device has too little free space for a
copy of ``model``. With ``server`` isolation every worker starts its own container and uses ``sybase_database``.

``exec_isql`` and ``SybaseService.exec_sql`` run ``isql --retserverror -b`` against ``127.0.0.1:5000`` inside the
container and return a non-zero exit code for server errors of severity 11 or higher.

Available Fixtures
------------------

* ``sybase_image``: Docker image tag for SAP Sybase ASE (default: ``datagrip/sybase:16.0``, env ``SYBASE_IMAGE``).
* ``sybase_user``: Login user for the Sybase ASE instance (default: ``sa``, env ``SYBASE_USER``).
* ``sybase_password``: Login password for the Sybase ASE instance (default: ``myPassword``, env ``SYBASE_PASSWORD``).
  The default image's ``sa`` password is fixed to ``myPassword``.
* ``sybase_database``: Database the service uses outside ``pytest-xdist`` and the base name of the worker databases
  (default: ``master``, env ``SYBASE_DATABASE``). Any value other than ``master`` is created on startup.
* ``sybase_startup_timeout``: Timeout in seconds for container startup (default: ``300``, env
  ``SYBASE_STARTUP_TIMEOUT``).
* ``xdist_sybase_isolation_level``: Worker isolation mode (default: ``database``).
* ``sybase_service``: Provides a running Sybase ASE service container.

Service API
-----------

.. automodule:: pytest_databases.docker.sybase
   :members:
   :undoc-members:
   :show-inheritance:
