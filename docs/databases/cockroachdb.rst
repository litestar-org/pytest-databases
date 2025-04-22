\
.. _db_cockroachdb:

CockroachDB
===========

Integration with CockroachDB.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[cockroachdb]

Docker Image
------------

`Official CockroachDB Docker Image <https://hub.docker.com/r/cockroachdb/cockroach/>`_

Configuration
-------------

* ``COCKROACHDB_IMAGE``: Docker image to use for CockroachDB (default: "cockroachdb/cockroach:latest")
* ``XDIST_COCKROACHDB_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``COCKROACHDB_DATABASE``: Database name for CockroachDB (default: "pytest_databases")

API
---

.. automodule:: pytest_databases.docker.cockroachdb
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
