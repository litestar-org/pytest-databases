Redis
=====

Integration with `Redis <https://redis.io/>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[redis]

Usage Example
-------------

.. code-block:: python

    import pytest
    import redis
    from pytest_databases.docker.redis import RedisService

    pytest_plugins = ["pytest_databases.docker.redis"]

    def test(redis_service: RedisService) -> None:
        client = redis.Redis(
            host=redis_service.host,
            port=redis_service.port,
            db=redis_service.db
        )
        client.set("test_key", "test_value")
        assert client.get("test_key") == b"test_value"

    def test(redis_connection: redis.Redis) -> None:
        redis_connection.set("test_key", "test_value")
        assert redis_connection.get("test_key") == b"test_value"

Available Fixtures
------------------

* ``redis_port``: The port number for the Redis service.
* ``redis_host``: The host name for the Redis service.
* ``redis_image``: The Docker image to use for Redis.
* ``redis_service``: A fixture that provides a Redis service.
* ``redis_connection``: A fixture that provides a Redis connection.

Service API
-----------

.. automodule:: pytest_databases.docker.redis
   :members:
   :undoc-members:
   :show-inheritance:
