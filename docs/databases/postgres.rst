\
.. _db_postgres:

PostgreSQL
==========

Integration with PostgreSQL.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[postgres]

Docker Image
------------

`Official PostgreSQL Docker Image <https://hub.docker.com/_/postgres>`_

Configuration
-------------

* ``POSTGRES_IMAGE``: Docker image to use for PostgreSQL (default: "postgres:latest")
* ``XDIST_POSTGRES_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``POSTGRES_USER``: Username for PostgreSQL (default: "postgres")
* ``POSTGRES_PASSWORD``: Password for PostgreSQL (default: "super-secret")
* ``POSTGRES_DB``: Database name for PostgreSQL (default: "pytest_databases")

API
---

.. automodule:: pytest_databases.docker.postgres
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
