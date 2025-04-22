\
.. _db_valkey:

Valkey
======

Integration with Valkey.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[valkey]

Docker Image
------------

`Official Valkey Docker Image <https://hub.docker.com/_/valkey>`_

Configuration
-------------

* ``VALKEY_IMAGE``: Docker image to use for Valkey (default: "valkey/valkey:latest")
* ``XDIST_VALKEY_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``VALKEY_DB``: Database number for Valkey (default: 0)

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
