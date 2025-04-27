Installation
============

First, install the base package using pip:

.. code-block:: bash

   pip install pytest-databases

Optional Database Support
~~~~~~~~~~~~~~~~~~~~~~~~~

To use ``pytest-databases`` with specific databases, you need to install optional dependencies using "extras". You can install support for one or multiple databases at once.

.. list-table:: Available Database Extras
   :widths: 25 50
   :header-rows: 1

   * - Database
     - Installation Extra
   * - PostgreSQL
     - ``pytest-databases[postgres]``
   * - MySQL
     - ``pytest-databases[mysql]``
   * - MariaDB
     - ``pytest-databases[mariadb]``
   * - Oracle
     - ``pytest-databases[oracle]``
   * - SQL Server
     - ``pytest-databases[sqlserver]``
   * - Google AlloyDB Omni
     - ``pytest-databases[alloydb]``
   * - Google Spanner
     - ``pytest-databases[spanner]``
   * - Google BigQuery
     - ``pytest-databases[bigquery]``
   * - CockroachDB
     - ``pytest-databases[cockroachdb]``
   * - Redis
     - ``pytest-databases[redis]``
   * - Valkey
     - ``pytest-databases[valkey]``
   * - Dragonfly
     - ``pytest-databases[dragonfly]``
   * - KeyDB
     - ``pytest-databases[keydb]``
   * - Elasticsearch
     - ``pytest-databases[elasticsearch]``
   * - Azure Blob Storage
     - ``pytest-databases[azure]``
   * - MinIO
     - ``pytest-databases[minio]``

Example installing multiple extras:

.. code-block:: bash

   pip install pytest-databases[postgres,mysql,redis]
