Oracle
======

Integration with `Oracle Database <https://www.oracle.com/database/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[oracle]

The ``oracle`` extra is retained as a compatibility install target and does not
install an Oracle Python client. If your tests need a Python client, install
your preferred client directly, for example:

.. code-block:: bash

   pip install oracledb

Usage Example
-------------

.. code-block:: python

    import pytest
    import oracledb
    from pytest_databases.docker.oracle import OracleService

    pytest_plugins = ["pytest_databases.docker.oracle"]

    def test(oracle_service: OracleService) -> None:
        # ``oracledb`` is user-owned application code; pytest-databases only
        # starts the service and provides connection metadata.
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

Available Fixtures
------------------

* ``oracle_user``: The application username created in the Oracle container.
* ``oracle_password``: The application user password.
* ``oracle_system_password``: The Oracle system password.
* ``oracle_service``: Alias for the latest supported Oracle service.

The following version-specific fixtures are also available:

* ``oracle_18c_image``, ``oracle_18c_service_name``, ``oracle_18c_service``: Oracle 18c
* ``oracle_23ai_image``, ``oracle_23ai_service_name``, ``oracle_23ai_service``: Oracle 23ai

Service API
-----------

.. automodule:: pytest_databases.docker.oracle
   :members:
   :undoc-members:
   :show-inheritance:
