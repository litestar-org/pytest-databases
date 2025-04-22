\
.. _db_spanner:

Google Spanner
==============

Integration with Google Spanner Emulator.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[spanner]

Emulator
--------

`Spanner Emulator <https://cloud.google.com/spanner/docs/emulator>`_

Configuration
-------------

* ``SPANNER_IMAGE``: Docker image to use for Spanner (default: "gcr.io/cloud-spanner-emulator/emulator:latest")
* ``XDIST_SPANNER_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "server")
* ``SPANNER_PROJECT``: Project ID for Spanner (default: "emulator-test-project")
* ``SPANNER_INSTANCE``: Instance name for Spanner (default: "emulator-test-instance")
* ``SPANNER_DATABASE``: Database name for Spanner (default: "emulator-test-database")

API
---

.. automodule:: pytest_databases.docker.spanner
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
