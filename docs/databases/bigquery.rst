\
.. _db_bigquery:

Google BigQuery
===============

Integration with an unofficial Google BigQuery Emulator.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[bigquery]

Emulator
--------

`BigQuery Emulator (Unofficial) <https://github.com/goccy/bigquery-emulator>`_

Configuration
-------------

* ``BIGQUERY_IMAGE``: Docker image to use for BigQuery (default: "ghcr.io/goccy/bigquery-emulator:latest")
* ``XDIST_BIGQUERY_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "server")
* ``BIGQUERY_PROJECT``: Project ID for BigQuery (default: "test-project")
* ``BIGQUERY_DATASET``: Dataset name for BigQuery (default: "test_dataset")

API
---

.. automodule:: pytest_databases.docker.bigquery
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
