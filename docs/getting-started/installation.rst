Installation
============

``pytest-databases`` requires Python 3.11 or later.

.. tab-set::
   :sync-group: installer

   .. tab-item:: uv
      :sync: uv

      .. code-block:: bash

         uv add --dev pytest-databases

   .. tab-item:: pip
      :sync: pip

      .. code-block:: bash

         pip install pytest-databases

   .. tab-item:: pdm
      :sync: pdm

      .. code-block:: bash

         pdm add --dev pytest-databases

   .. tab-item:: poetry
      :sync: poetry

      .. code-block:: bash

         poetry add --group dev pytest-databases

All ``*_service`` container fixtures check readiness with Python's standard library or with tools bundled inside the
container image, so the base package does not install any database driver. Install the client library your application
already uses alongside ``pytest-databases``.

Optional Extras
~~~~~~~~~~~~~~~

The extras below remain for projects that pin ``pytest-databases[<extra>]``. None of them is needed by a ``*_service``
fixture; the ones that install a package only pull in a client for your own tests or for a deprecated client fixture.

.. list-table:: Available extras
   :widths: 25 35 40
   :header-rows: 1

   * - Extra
     - Installs
     - Notes
   * - ``azure``, ``azure-blob``, ``azure-storage``
     - ``azure-storage-blob``
     - Same contents. ``azure-storage`` is the v0.19.0 name.
   * - ``bigquery``
     - ``google-cloud-bigquery``
     - Used by the deprecated ``bigquery_client`` fixture.
   * - ``gizmosql``
     - ``adbc-driver-flightsql``, ``pyarrow``
     - Used by the deprecated ``gizmosql_connection`` fixture.
   * - ``postgres``
     - ``psycopg>=3``
     - Used by the deprecated PostgreSQL-family ``*_connection`` fixtures.
   * - ``redis``, ``dragonfly``, ``keydb``
     - ``redis``
     - Same contents.
   * - ``spanner``
     - ``google-cloud-spanner``
     - Used by the deprecated ``spanner_connection`` fixture.
   * - ``cockroachdb``, ``elasticsearch7``, ``elasticsearch8``, ``mongodb``, ``oracle``, ``valkey``
     - nothing
     - Installed a driver in v0.19.0 (``psycopg``, ``elasticsearch7``, ``elasticsearch8``, ``pymongo``,
       ``oracledb``, ``valkey``). Install the driver directly if you use the deprecated client fixtures.
   * - ``mariadb``, ``mssql``, ``mysql``, ``yugabyte``
     - nothing
     - Empty since v0.19.0.

Providers without an extra (Db2, Dolt, Floci, LocalStack, MinIO, Pub/Sub, RabbitMQ, Redpanda, RustFS, Snowflake, and
the rest) only need the base package.
