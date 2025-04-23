Spanner
=======

Integration with `Google Cloud Spanner <https://cloud.google.com/spanner>`_ using the `Spanner Emulator <https://cloud.google.com/spanner/docs/emulator>`_

This integration uses the official `Google Cloud Spanner Python Client <https://cloud.google.com/python/docs/reference/spanner/latest>`_ for testing against the Spanner Emulator. The emulator provides a local development environment that mimics the behavior of Cloud Spanner, allowing you to test your application without connecting to the actual service.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[spanner]

Usage Example
-------------

.. code-block:: python

    import pytest
    from google.cloud import spanner
    import contextlib
    from pytest_databases.docker.spanner import SpannerService

    pytest_plugins = ["pytest_databases.docker.spanner"]

    def test(spanner_service: SpannerService) -> None:
        spanner_client = spanner.Client(
            project=spanner_service.project,
            credentials=spanner_service.credentials,
            client_options=spanner_service.client_options,
        )
        instance = spanner_client.instance(spanner_service.instance_name)
        with contextlib.suppress(Exception):
            instance.create()

        database = instance.database(spanner_service.database_name)
        with contextlib.suppress(Exception):
            database.create()

        with database.snapshot() as snapshot:
            resp = next(iter(snapshot.execute_sql("SELECT 1")))
        assert resp[0] == 1

    def test(spanner_connection: spanner.Client) -> None:
        assert isinstance(spanner_connection, spanner.Client)

Available Fixtures
------------------

* ``spanner_image``: The Docker image to use for Spanner.
* ``spanner_service``: A fixture that provides a Spanner service.
* ``spanner_connection``: A fixture that provides a Spanner connection.

Service API
-----------

.. automodule:: pytest_databases.docker.spanner
   :members:
   :undoc-members:
   :show-inheritance:
