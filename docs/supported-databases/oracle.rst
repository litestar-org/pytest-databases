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
exposes both port ``1521`` (TCP / One-Way TLS) and port ``1522`` (mTLS), and
provides ``OracleADBService.extract_wallet(target_dir)`` to extract the TLS
wallet and rewrite ``tnsnames.ora`` with the mapped host and ports:

.. code-block:: python

   from pathlib import Path
   from pytest_databases.docker.oracle import OracleADBService, parse_tnsnames

   pytest_plugins = ["pytest_databases.docker.oracle"]


   def test_adb_wallet(oracle_adb_service: OracleADBService, tmp_path: Path) -> None:
       wallet_dir = oracle_adb_service.extract_wallet(tmp_path / "wallet")
       entries = parse_tnsnames((wallet_dir / "tnsnames.ora").read_text(encoding="utf-8"))
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
* ``oracle_adb_image``, ``oracle_adb_workload_type``, ``oracle_adb_hostname``,
  ``oracle_adb_wallet_password``, ``oracle_adb_service``: Oracle Autonomous Database Free (23ai)

Service API
-----------

.. automodule:: pytest_databases.docker.oracle
   :members:
   :undoc-members:
   :show-inheritance:
