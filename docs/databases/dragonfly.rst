\
.. _db_dragonfly:

Dragonfly
=========

Integration with Dragonfly.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[dragonfly]

Docker Image
------------

`Dragonfly Docker Documentation <https://www.dragonflydb.io/docs/getting-started/docker>`_

Configuration
-------------

* ``DRAGONFLY_IMAGE``: Docker image to use for Dragonfly (default: "dragonflydb/dragonfly:latest")
* ``XDIST_DRAGONFLY_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``DRAGONFLY_DB``: Database number for Dragonfly (default: 0)

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
