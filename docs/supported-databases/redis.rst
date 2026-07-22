Redis
=====

Integration with `Redis <https://redis.io/>`_ using the `Redis Docker Image <https://hub.docker.com/_/redis>`_, `KeyDB <https://docs.keydb.dev/>`_, or `Dragonfly <https://www.dragonflydb.io/>`_. KeyDB and Dragonfly are wire-compatible with Redis, so a ``redis.Redis`` client works against all three services.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[redis] redis

The ``redis`` package is no longer pulled by the ``pytest-databases[redis]`` extra — the fixtures validate the container via ``redis-cli`` invoked from a short-lived sidecar — so install your own client (``redis``, ``redis[hiredis]``, etc.) alongside ``pytest-databases``.

Usage Example
-------------

.. code-block:: python

    import pytest
    import redis
    from pytest_databases.docker.redis import RedisService

    pytest_plugins = ["pytest_databases.docker.redis"]

    def test_redis(redis_service: RedisService) -> None:
        client = redis.Redis(
            host=redis_service.host,
            port=redis_service.port,
            db=redis_service.db,
        )
        client.set("test_key", "test_value")
        assert client.get("test_key") == b"test_value"

    def test_keydb(keydb_service: RedisService) -> None:
        client = redis.Redis(host=keydb_service.host, port=keydb_service.port, db=keydb_service.db)
        client.set("test_key", "test_value")
        assert client.get("test_key") == b"test_value"

    def test_dragonfly(dragonfly_service: RedisService) -> None:
        client = redis.Redis(host=dragonfly_service.host, port=dragonfly_service.port, db=dragonfly_service.db)
        client.set("test_key", "test_value")
        assert client.get("test_key") == b"test_value"

Available Fixtures
------------------

* ``redis_port``: The port number for the Redis service.
* ``redis_host``: The host name for the Redis service.
* ``redis_image``: The Docker image to use for Redis.
* ``redis_service``: A fixture that provides a ``RedisService`` (``host``, ``port``, ``container``, ``db``).

The following compatible-service fixtures are also available:

* ``dragonfly_port``, ``dragonfly_host``, ``dragonfly_image``, ``dragonfly_service``: Latest available DragonflyDB Docker image.
* ``keydb_port``, ``keydb_host``, ``keydb_image``, ``keydb_service``: Latest available KeyDB Docker image.

Service API
-----------

.. automodule:: pytest_databases.docker.redis
   :members:
   :undoc-members:
   :show-inheritance:
