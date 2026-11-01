Snowflake (Embucket)
====================

Integration with `Embucket <https://github.com/embucket/embucket>`_, a
Snowflake-compatible SQL analytics and Apache Iceberg emulator (`embucket/embucket:latest`).
The fixture is clientless and validates readiness and SQL execution over
Python's standard library ``urllib.request`` without requiring
``snowflake-connector-python`` in the base package.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``snowflake-connector-python`` in your project if your application connects
using the official Snowflake Python connector.

Usage Example
-------------

``SnowflakeService.query()`` executes SQL directly against Embucket's
``/queries/v1/query-request`` endpoint, and ``SnowflakeService.connection_kwargs``
provides connection parameters for ``snowflake.connector.connect``:

.. code-block:: python

   from pytest_databases.docker.snowflake import SnowflakeService

   pytest_plugins = ["pytest_databases.docker.snowflake"]


   def test_snowflake(snowflake_service: SnowflakeService) -> None:
       response = snowflake_service.query("SELECT 1")
       assert response.get("success") is True
       assert snowflake_service.connection_kwargs["protocol"] == "http"

Available Fixtures
------------------

* ``snowflake_image``: Container image (default: ``embucket/embucket:latest``).
* ``snowflake_user``, ``snowflake_password``, ``snowflake_account``
* ``snowflake_database``, ``snowflake_schema``, ``snowflake_warehouse``, ``snowflake_role``
* ``xdist_snowflake_isolation_level``: ``"database"`` (worker-scoped schema) or ``"server"``
* ``snowflake_service`` and ``embucket_service``: :class:`~pytest_databases.docker.snowflake.SnowflakeService`

Service API
-----------

.. automodule:: pytest_databases.docker.snowflake
   :members:
   :undoc-members:
   :show-inheritance:
