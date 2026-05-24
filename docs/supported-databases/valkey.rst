Valkey
======

Integration with `Valkey <https://valkey.io/>`_ using the `Valkey Docker Image <https://hub.docker.com/_/valkey>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[valkey] valkey

The ``valkey`` Python client is no longer pulled by ``pytest-databases[valkey]`` — the fixture validates the container via the bundled ``valkey-cli`` invoked through ``container.exec_run`` — so install your own client alongside ``pytest-databases``.

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
            db=valkey_service.db,
        )
        client.set("test_key", "test_value")
        assert client.get("test_key") == b"test_value"

Available Fixtures
------------------

* ``valkey_port``: The port number for the Valkey service.
* ``valkey_host``: The host name for the Valkey service.
* ``valkey_image``: The Docker image to use for Valkey.
* ``valkey_service``: A fixture that provides a ``ValkeyService`` (``host``, ``port``, ``container``, ``db``).

Service API
-----------

.. automodule:: pytest_databases.docker.valkey
   :members:
   :undoc-members:
   :show-inheritance:
