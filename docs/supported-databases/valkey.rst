Valkey
======

Integration with `Valkey <https://valkey.io/>`_ using the `Valkey Docker Image <https://hub.docker.com/_/valkey>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases valkey

The ``valkey`` extra no longer installs the ``valkey`` client. Readiness is verified over a Python stdlib TCP socket using the RESP protocol, so install your own client alongside ``pytest-databases``.

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
* ``xdist_valkey_isolation_level``: ``database`` (default) or ``server``.

Under ``pytest-xdist`` with ``database`` isolation, workers share one container and each worker uses its own
logical database (``ValkeyService.db``). Every 16 workers get an additional shared container. With ``server``
isolation every worker gets its own container.

Service API
-----------

.. automodule:: pytest_databases.docker.valkey
   :members:
   :undoc-members:
   :show-inheritance:
