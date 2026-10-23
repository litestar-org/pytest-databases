Oracle
======

Integration with `Oracle Database <https://www.oracle.com/database/>`_ and
Oracle Autonomous Database Free (``adb-free:latest-23ai``).

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

Autonomous Database Free (23ai)
-------------------------------

``oracle_adb_service`` starts the official
``container-registry.oracle.com/database/adb-free:latest-23ai`` container image,
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

Available Fixtures
------------------

* ``oracle_user``: The application username created in the Oracle container.
* ``oracle_password``: The application user password.
* ``oracle_system_password``: The Oracle system password.
* ``oracle_service``: Alias for the latest supported Oracle service.

The following version-specific and Autonomous Database fixtures are also available:

* ``oracle_18c_image``, ``oracle_18c_service_name``, ``oracle_18c_service``: Oracle 18c XE
* ``oracle_23ai_image``, ``oracle_23ai_service_name``, ``oracle_23ai_service``: Oracle 23ai Free
* ``oracle_adb_image``, ``oracle_adb_workload_type`` (``ATP``, ``ADW``, ``AJD``, ``APEX``),
  ``oracle_adb_hostname``, ``oracle_adb_tz``, ``oracle_adb_password``,
  ``oracle_adb_admin_password``, ``oracle_adb_wallet_password``,
  ``oracle_adb_wallet_dir``, ``oracle_adb_volumes``, ``oracle_adb_devices``,
  ``oracle_adb_filesystemio_options`` (default ``NONE``, env ``ORACLE_ADB_FILESYSTEMIO_OPTIONS``),
  ``oracle_adb_service``:
  Oracle Autonomous Database Free (23ai)

Service API
-----------

.. automodule:: pytest_databases.docker.oracle
   :members:
   :undoc-members:
   :show-inheritance:
