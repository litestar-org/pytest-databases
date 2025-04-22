\
.. _db_alloydb:

Google AlloyDB Omni
===================

Integration with Google AlloyDB Omni.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[alloydb]

Docker Image / Installation
---------------------------

`AlloyDB Omni Documentation <https://cloud.google.com/alloydb/omni/docs/introduction>`_

Configuration
-------------

* ``ALLOYDB_OMNI_IMAGE``: Docker image to use for AlloyDB Omni (default: "gcr.io/cloud-sql-connectors/alloydb-omni:latest")
* ``XDIST_ALLOYDB_OMNI_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "server")

API
---

.. automodule:: pytest_databases.docker.alloydb_omni
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
