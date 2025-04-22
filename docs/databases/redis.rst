.. _redis:

Redis
=====

Integration with Redis.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[redis]

Docker Image
------------

`Official Redis Docker Image <https://hub.docker.com/_/redis>`_

Configuration
-------------

* ``REDIS_IMAGE``: Docker image to use for Redis (default: "redis:latest")
* ``XDIST_REDIS_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``REDIS_DB``: Database number for Redis (default: 0)

API
---

.. automodule:: pytest_databases.docker.redis
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
