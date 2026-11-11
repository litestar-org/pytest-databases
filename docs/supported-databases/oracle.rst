Oracle
======

Integration with `Oracle AI Database <https://www.oracle.com/database/>`_ (18c XE
and 26ai Free) and Oracle Autonomous AI Database Free
(``adb-free:latest-26ai``).

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``oracledb`` in your project if your tests connect from the host. The
service fixtures themselves validate readiness using ``sqlplus`` inside the
container and do not require ``oracledb`` in the base package.

Usage Example
-------------

.. code-block:: python

   import oracledb
   from pytest_databases.docker.oracle import OracleService

   pytest_plugins = ["pytest_databases.docker.oracle"]


   def test(oracle_service: OracleService) -> None:
       conn = oracledb.connect(
           user=oracle_service.user,
           password=oracle_service.password,
           service_name=oracle_service.service_name,
           host=oracle_service.host,
           port=oracle_service.port,
       )
       with conn.cursor() as cur:
           cur.execute("SELECT 1 FROM dual")
           res = cur.fetchone()[0]
           assert res == 1

Autonomous AI Database Free (26ai)
----------------------------------

``oracle_adb_service`` starts the official
``container-registry.oracle.com/database/adb-free:latest-26ai`` container image,
exposes all four Autonomous Database ports (``1521`` TLS, ``1522`` mTLS,
``8443`` ORDS / APEX / SQL Developer Web HTTPS, and ``27017`` Oracle Database
API for MongoDB), provisions the test user via the ``ADMIN`` account on the
``DATA`` tablespace with ``DWROLE``, REST-enables the schema via
``ORDS.ENABLE_SCHEMA``, and automatically extracts the TLS/mTLS wallet to
``oracle_adb_service.wallet_dir`` with ``tnsnames.ora`` and ``sqlnet.ora``
rewritten for the mapped host and ports. A failure while provisioning the user
or REST-enabling the schema fails the fixture with the SQL*Plus error. An
unknown ``oracle_adb_workload_type`` raises ``ValueError``. The container gets
``SYS_ADMIN`` and no devices by default; override ``oracle_adb_devices`` (for
example ``["/dev/fuse"]``) when the container runtime host provides them.

The image's server parameter file sets ``filesystemio_options`` to direct I/O,
which cannot open the control files when the container storage has 4096-byte
logical sectors (for example an overlay2 Docker root on a 4Kn or dm-crypt
device): startup fails with ``ORA-27072`` / ``ORA-00202`` and then ``ORA-01034``.
``oracle_adb_service`` therefore rewrites the server parameter file with
``filesystemio_options='NONE'`` before the image entrypoint starts the database
(``CREATE PFILE FROM SPFILE`` and ``CREATE SPFILE FROM PFILE`` against the idle
instance, inside the container). ``NONE`` also works on 512-byte storage.
Override ``oracle_adb_filesystemio_options`` to choose another value, or return
``None`` to start the image unchanged:

.. code-block:: python

   import pytest


   @pytest.fixture(scope="session")
   def oracle_adb_filesystemio_options() -> str | None:
       return None

The wallet and endpoints are available on the service:

.. code-block:: python

   from pathlib import Path
   from pytest_databases.docker.oracle import OracleADBService, parse_tnsnames

   pytest_plugins = ["pytest_databases.docker.oracle"]


   def test_adb_wallet_and_endpoints(oracle_adb_service: OracleADBService, tmp_path: Path) -> None:
       assert oracle_adb_service.wallet_dir is not None
       assert oracle_adb_service.ca_cert_path is not None
       assert oracle_adb_service.ords_url.startswith("https://")
       assert oracle_adb_service.apex_url.endswith("/ords/apex")
       assert oracle_adb_service.sql_developer_url.endswith("/ords/sql-developer")
       assert "authMechanism=PLAIN" in oracle_adb_service.mongo_uri
       entries = parse_tnsnames((oracle_adb_service.wallet_dir / "tnsnames.ora").read_text(encoding="utf-8"))
       assert "myatp_high" in entries

Parallel Execution
------------------

By default, ``xdist_oracle_isolation_level`` returns ``"database"``. Under
``pytest-xdist``, workers share one container per Oracle flavor
(``oracle26ai``, ``oracle18c``, and ``oracle_adb``) and each worker receives
an isolated user named ``<oracle_user>_<worker>`` (for example ``app_0`` and
``app_1``). Both single-process and ``pytest-xdist`` sessions provision the
active user via :func:`~pytest_databases.docker.oracle.ensure_oracle_user`
under a cross-worker file lock with identical ``CONNECT``, ``RESOURCE``, and
``DBA`` roles plus ``QUOTA UNLIMITED ON USERS``, idempotently tolerating
``ORA-01920`` and retrying transient ``ORA-*`` startup or lock errors.

:meth:`~pytest_databases.docker.oracle.OracleService.exec_sql` and
:func:`~pytest_databases.docker.oracle.exec_oracle_sql` run SQL or PL/SQL
through in-container ``sqlplus`` against either a pluggable database service
or ``CDB$ROOT`` (``cdb_root=True`` / ``sqlplus -L -S / as sysdba``). Custom
fixtures calling :func:`~pytest_databases.docker.oracle.provide_oracle_service`
or :func:`~pytest_databases.docker.oracle.provide_oracle_adb_service` can also
pass ``host_port``, ``env``, ``volumes``, ``shm_size``, ``mem_limit``, and
one-shot ``init_sql`` scripts.

High-concurrency suites that open unpooled per-test connections against the
shared container (for example, SQLAlchemy ``NullPool`` across large test suites
without ``oracledb`` ``retry_count``) can briefly exhaust TNS listener handlers
and fail with ``ORA-12516`` (``DPY-6000``). Resolve listener contention using
either of the following options:

1. Enable connection pooling instead of ``NullPool``, or configure ``oracledb``
   ``retry_count`` and ``retry_delay`` in your driver connection arguments so
   transient listener refusals retry automatically.
2. Override ``xdist_oracle_isolation_level`` to return ``"server"`` so each
   worker runs a dedicated transient container and listener (at higher memory
   and startup cost):

.. code-block:: python

   import pytest
   from pytest_databases.types import XdistIsolationLevel


   @pytest.fixture(scope="session")
   def xdist_oracle_isolation_level() -> XdistIsolationLevel:
       return "server"

Available Fixtures
------------------

* ``oracle_user``: The application username created in the Oracle container (default: ``"app"``, env ``ORACLE_USER``).
* ``oracle_password``: The application user password (default: ``"super-secret"``, env ``ORACLE_PASSWORD``).
* ``oracle_system_password``: The Oracle system password (default: ``"super-secret"``, env ``ORACLE_SYSTEM_PASSWORD``).
* ``oracle_port``: Optional pinned host port for the default Oracle container (default: ``None``, env ``ORACLE_PORT``).
* ``xdist_oracle_isolation_level``: Worker isolation mode: ``"database"`` (default,
  shared container with per-worker users) or ``"server"`` (one transient container
  per worker).
* ``oracle_startup_timeout``: Startup timeout in seconds for ``oracle_18c_service``
  and ``oracle_26ai_service`` (default ``180``, env
  ``ORACLE_STARTUP_TIMEOUT``; non-integer or non-positive values raise ``ValueError``).
* ``oracle_adb_startup_timeout``: Startup timeout in seconds for
  ``oracle_adb_service`` (default ``420``, env ``ORACLE_ADB_STARTUP_TIMEOUT``;
  non-integer or non-positive values raise ``ValueError``).
* ``oracle_service``: Alias for the latest supported Oracle service (``oracle_26ai_service``).

The following version-specific and Autonomous Database fixtures are also available:

* ``oracle_18c_image``, ``oracle_18c_service_name``, ``oracle_18c_port`` (env ``ORACLE_18C_PORT``), ``oracle_18c_service``: Oracle 18c XE
* ``oracle_26ai_image`` (default ``gvenzl/oracle-free:23-slim-faststart``, delivering the ``23.26.x`` Oracle AI Database 26ai Free release line; env ``ORACLE_26AI_IMAGE``), ``oracle_26ai_service_name`` (default ``FREEPDB1``, env ``ORACLE_26AI_SERVICE_NAME``), ``oracle_26ai_port`` (env ``ORACLE_26AI_PORT``, falling back to ``oracle_port``), ``oracle_26ai_service``: Oracle AI Database 26ai Free. The ``v0.19.0`` ``oracle_23ai_image``, ``oracle_23ai_service_name``, ``oracle_23ai_service``, and ``oracle_23ai_connection`` fixtures (and external overrides of ``oracle_23ai_image``, ``oracle_23ai_service_name``, and ``oracle_23ai_service``) remain available as deprecated aliases until ``v1.0.0``.
* ``oracle_adb_image``, ``oracle_adb_workload_type`` (``ATP``, ``ADW``, ``AJD``, ``APEX``),
  ``oracle_adb_hostname``, ``oracle_adb_tz``, ``oracle_adb_password``,
  ``oracle_adb_admin_password``, ``oracle_adb_wallet_password``,
  ``oracle_adb_wallet_dir``, ``oracle_adb_volumes``, ``oracle_adb_devices``,
  ``oracle_adb_filesystemio_options`` (default ``NONE``, env ``ORACLE_ADB_FILESYSTEMIO_OPTIONS``),
  ``oracle_adb_port`` (env ``ORACLE_ADB_PORT``), ``oracle_adb_service``:
  Oracle Autonomous AI Database Free (26ai)

Service API
-----------

.. automodule:: pytest_databases.docker.oracle
   :members:
   :undoc-members:
   :show-inheritance:
