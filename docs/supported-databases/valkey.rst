Valkey
======

Integration with `Valkey <https://valkey.io//>`_ using the `Valkey Docker Image <https://hub.docker.com/_/valkey>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[valkey]

Usage Example
-------------

.. code-block:: python

    import pytest
    from valkey import Valkey
    from pytest_databases.docker.valkey import ValkeyService

    pytest_plugins = ["pytest_databases.docker.valkey"]

    def test(valkey_service: ValkeyService) -> None:
        client = Valkey(
            host=valkey_service.host,
            port=valkey_service.port,
            db=valkey_service.db
        )
        client.set("test_key", "test_value")
        assert client.get("test_key") == b"test_value"

    def test(valkey_connection: Valkey) -> None:
        valkey_connection.set("test_key", "test_value")
        assert valkey_connection.get("test_key") == b"test_value"

Available Fixtures
------------------

* ``valkey_port``: The port number for the Valkey service.
* ``valkey_host``: The host name for the Valkey service.
* ``valkey_image``: The Docker image to use for Valkey.
* ``valkey_service``: A fixture that provides a Valkey service.
* ``valkey_connection``: A fixture that provides a Valkey connection.

Service API
-----------

.. automodule:: pytest_databases.docker.valkey
   :members:
   :undoc-members:
   :show-inheritance:
