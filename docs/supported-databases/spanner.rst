Spanner
=======

Integration with `Google Cloud Spanner <https://cloud.google.com/spanner>`_ using the `Spanner Emulator <https://cloud.google.com/spanner/docs/emulator>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Bring your own client (for example ``google-cloud-spanner``).

Usage Example
-------------

.. code-block:: python

    import contextlib

    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import spanner

    from pytest_databases.docker.spanner import SpannerService

    pytest_plugins = ["pytest_databases.docker.spanner"]


    def test(spanner_service: SpannerService) -> None:
        client = spanner.Client(
            project=spanner_service.project,
            credentials=AnonymousCredentials(),
            client_options=ClientOptions(api_endpoint=spanner_service.endpoint),
        )
        instance = client.instance(spanner_service.instance_name)
        with contextlib.suppress(Exception):
            instance.create()

        database = instance.database(spanner_service.database_name)
        with contextlib.suppress(Exception):
            database.create()

        with database.snapshot() as snapshot:
            row = next(iter(snapshot.execute_sql("SELECT 1")))
        assert row[0] == 1

Available Fixtures
------------------

* ``spanner_image``: The Docker image to use for Spanner.
* ``spanner_service``: A fixture that provides a Spanner service.

Service API
-----------

.. automodule:: pytest_databases.docker.spanner
   :members:
   :undoc-members:
   :show-inheritance:
