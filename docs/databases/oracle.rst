Oracle
======

Integration with `Oracle Database <https://www.oracle.com/database/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[oracle]

Usage Example
-------------

.. code-block:: python

    import pytest
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

    def test(oracle_startup_connection: oracledb.Connection) -> None:
        with oracle_startup_connection.cursor() as cursor:
            cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
            cursor.execute("select * from simple_table")
            result = cursor.fetchall()
            assert result is not None and result[0][0] == 1

Available Fixtures
------------------

* ``oracle_image``: The Docker image to use for Oracle.
* ``oracle_service``: A fixture that provides an Oracle service.
* ``oracle_startup_connection``: A fixture that provides an Oracle connection.

The following version-specific fixtures are also available:

* ``oracle_18c_image``, ``oracle_18c_service_name``, ``oracle_18c_service``, ``oracle_18c_connection``: Oracle 18c
* ``oracle_23ai_image``, ``oracle_23ai_service_name``, ``oracle_23ai_service``, ``oracle_23ai_connection``: Oracle 23ai

Service API
-----------

.. automodule:: pytest_databases.docker.oracle
   :members:
   :undoc-members:
   :show-inheritance:
