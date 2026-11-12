Snowflake (Embucket)
====================

Integration with `Embucket <https://github.com/embucket/embucket>`_, a Snowflake-compatible SQL and Apache Iceberg
engine (default image ``embucket/embucket:0.2.2``, HTTP port ``3000``). The fixture is clientless: readiness, login,
and SQL execution use Python's standard library, so ``snowflake-connector-python`` is not required.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``snowflake-connector-python`` in your project if your application connects with the official Snowflake
Python connector.

Usage Example
-------------

Embucket always requires a login. ``SnowflakeService.query()`` logs in through ``/session/v1/login-request`` as
``snowflake_user`` / ``snowflake_password`` on first use, caches the session token, and runs SQL through
``/queries/v1/query-request`` with ``snowflake_database`` and ``snowflake_schema`` as the session's current database
and schema. ``SnowflakeService.connection_kwargs`` provides parameters for ``snowflake.connector.connect``:

.. code-block:: python

   from pytest_databases.docker.snowflake import (
       SnowflakeService,
       login_snowflake_emulator,
       query_snowflake_emulator,
   )

   pytest_plugins = ["pytest_databases.docker.snowflake"]


   def test_snowflake(snowflake_service: SnowflakeService) -> None:
       token = login_snowflake_emulator(snowflake_service)
       response = query_snowflake_emulator(snowflake_service, token, "SELECT 1")
       assert response["success"] is True
       assert response["data"]["rowset"] == [["1"]]
       assert snowflake_service.connection_kwargs["protocol"] == "http"

``query()`` raises ``RuntimeError`` with the emulator's message when a statement fails. By default,
``snowflake_wire_compat`` (``SNOWFLAKE_WIRE_COMPAT``, default ``True``) runs a loopback REST v1 compatibility proxy in
front of Embucket that decompresses ``Content-Encoding: gzip`` request payloads, substitutes positional ``?``
``bindings`` parameters in SQL text, and stringifies non-``None`` ``rowset`` cells (such as ``[["1"]]``) for
``snowflake-connector-python``. Set ``SNOWFLAKE_WIRE_COMPAT=0`` (or override ``snowflake_wire_compat`` to ``False`` and
pass ``wire_compat=False`` to ``provide_snowflake_service``) to target the raw Embucket port directly (``[[1]]``).

The container is started with ``snowflake_user`` and ``snowflake_password`` as its login (``AUTH_DEMO_USER`` /
``AUTH_DEMO_PASSWORD``) and an in-memory volume that holds ``snowflake_database`` and its ``public`` schema. Data
does not survive a container restart.

Isolation
---------

With the default ``xdist_snowflake_isolation_level`` (``database``) all pytest-xdist workers share one container, and
each worker gets its own schema ``public_<worker>``, created before the service is yielded; unqualified table names in
``query()`` resolve to that schema. With ``server`` each worker starts its own container named
``snowflake_<worker>`` and uses ``public``.

Available Fixtures
------------------

* ``snowflake_image``: Container image (default ``embucket/embucket:0.2.2``, env ``SNOWFLAKE_IMAGE``).
* ``snowflake_user``, ``snowflake_password`` (default ``embucket`` / ``embucket``), ``snowflake_account``
* ``snowflake_database``, ``snowflake_schema``, ``snowflake_warehouse``, ``snowflake_role``
* ``snowflake_wire_compat``: Enable the REST v1 compatibility loopback proxy (default ``True``, env ``SNOWFLAKE_WIRE_COMPAT``).
* ``xdist_snowflake_isolation_level``: ``"database"`` (worker-scoped schema) or ``"server"``
* ``snowflake_service``: :class:`~pytest_databases.docker.snowflake.SnowflakeService`

Service API
-----------

.. automodule:: pytest_databases.docker.snowflake
   :members:
   :undoc-members:
   :show-inheritance:
