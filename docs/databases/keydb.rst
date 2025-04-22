\
.. _db_keydb:

KeyDB
=====

Integration with KeyDB.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[keydb]

Docker Image
------------

`KeyDB Docker Image <https://hub.docker.com/r/eqalpha/keydb>`_

Configuration
-------------

* ``KEYDB_IMAGE``: Docker image to use for KeyDB (default: "eqalpha/keydb:latest")
* ``XDIST_KEYDB_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``KEYDB_DB``: Database number for KeyDB (default: 0)

API
---

See the :ref:`redis documentation <redis>` for details on available fixtures and configuration options.

API Reference
-------------

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
