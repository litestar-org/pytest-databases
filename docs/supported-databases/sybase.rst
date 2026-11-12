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


   def test_sybase_freetds_alias(sybase_service: SybaseService, sybase_freetds_alias: str) -> None:
       with pymssql.connect(
           server=sybase_freetds_alias,
           user=sybase_service.user,
           password=sybase_service.password,
           database=sybase_service.database,
           autocommit=True,
       ) as conn, conn.cursor() as cur:
           cur.execute("SELECT 1")
           res = cur.fetchone()[0]
           assert res == 1

FreeTDS 5.0 Client Configuration
--------------------------------

FreeTDS builds targeting TDS 7.x by default (for MS SQL Server) require ``tds version = 5.0`` to talk to SAP ASE.
``sybase_freetds_alias`` writes a dedicated server block via :meth:`~pytest_databases.docker.sybase.SybaseService.write_freetds_conf`
(preserving existing server sections in ``FREETDSCONF`` without mutating ``[global]`` ``tds version``), sets
``FREETDSCONF`` for the session, and restores the prior environment variable at teardown so concurrent MS SQL Server
clients remain unaffected.

Parallel Execution
------------------

With the default ``database`` isolation, ``pytest-xdist`` workers share one container and each worker gets its own
database: ``<sybase_database>_<worker>``, or ``pytestdb_<worker>`` when ``sybase_database`` is ``master``. The name must
be a valid ASE identifier of at most 30 characters. Each database is created on its own ``<database>_dev`` device
(48 MB) next to the ``master`` device, because the default image's ``master`` device has too little free space for a
copy of ``model``. With ``server`` isolation every worker starts its own container and uses ``sybase_database``.

``exec_isql`` and ``SybaseService.exec_sql`` run ``isql --retserverror -b`` against ``127.0.0.1:5000`` inside the
container and return a non-zero exit code for server errors of severity 11 or higher. Set ``SYBASE_ENABLE_MONITORING=1``
(or override ``sybase_enable_monitoring`` to return ``True``) to run
:func:`~pytest_databases.docker.sybase.configure_sybase_monitoring` once per container, enabling the ASE ``mon*`` MDA
monitoring parameters via ``sp_configure`` and granting ``mon_role`` to non-``sa`` logins. Custom fixtures calling
:func:`~pytest_databases.docker.sybase.provide_sybase_service` can also pass ``host_port``, ``env``, and one-shot
``init_sql`` scripts.

Available Fixtures
------------------

* ``sybase_image``: Docker image tag for SAP Sybase ASE (default: ``datagrip/sybase:16.0``, env ``SYBASE_IMAGE``).
* ``sybase_user``: Login user for the Sybase ASE instance (default: ``sa``, env ``SYBASE_USER``).
* ``sybase_password``: Login password for the Sybase ASE instance (default: ``myPassword``, env ``SYBASE_PASSWORD``).
  The default image's ``sa`` password is fixed to ``myPassword``.
* ``sybase_database``: Database the service uses outside ``pytest-xdist`` and the base name of the worker databases
  (default: ``master``, env ``SYBASE_DATABASE``). Any value other than ``master`` is created on startup.
* ``sybase_port``: Optional pinned host TCP port (default: ``None``, env ``SYBASE_PORT``).
* ``sybase_enable_monitoring``: Enable SAP ASE ``mon*`` MDA monitoring tables on startup (default: ``False``, env
  ``SYBASE_ENABLE_MONITORING``).
* ``sybase_startup_timeout``: Timeout in seconds for container startup (default: ``300``, env
  ``SYBASE_STARTUP_TIMEOUT``).
* ``xdist_sybase_isolation_level``: Worker isolation mode (default: ``database``).
* ``sybase_service``: Provides a running Sybase ASE service container.
* ``sybase_freetds_alias``: Session-scoped server alias configured in ``FREETDSCONF`` with ``tds version = 5.0`` (via ``SybaseService.write_freetds_conf``).

Service API
-----------

.. automodule:: pytest_databases.docker.sybase
   :members:
   :undoc-members:
   :show-inheritance:
