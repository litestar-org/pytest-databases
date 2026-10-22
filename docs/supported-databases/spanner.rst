Spanner
=======

Integration with `Google Cloud Spanner <https://cloud.google.com/spanner>`_ using the `Spanner Emulator <https://cloud.google.com/spanner/docs/emulator>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[spanner]

Bring your own client (for example ``google-cloud-spanner``). The fixture provisions the test instance and database directly through the emulator's HTTP REST API on port ``9020`` without pulling a ``cloud-sdk`` sidecar image.

Usage Example
-------------

.. code-block:: python

    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import spanner
    from pytest_databases.docker.spanner import SpannerService

    pytest_plugins = ["pytest_databases.docker.spanner"]


    def test_spanner_service(spanner_service: SpannerService) -> None:
        client = spanner.Client(
            project=spanner_service.project,
            credentials=AnonymousCredentials(),
            client_options=ClientOptions(
                api_endpoint=f"{spanner_service.host}:{spanner_service.port}"
            ),
        )
        instance = client.instance(spanner_service.instance_name)
        database = instance.database(spanner_service.database_name)
        with database.snapshot() as snapshot:
            row = next(iter(snapshot.execute_sql("SELECT 1")))
        assert row[0] == 1

Available Fixtures
------------------

* ``spanner_image``: Container image for the Spanner emulator (default: ``gcr.io/cloud-spanner-emulator/emulator:latest``).
* ``spanner_project``: Google Cloud project ID (default: ``emulator-test-project``).
* ``spanner_instance_name``: Spanner instance ID (default: ``emulator-test-instance``).
* ``spanner_database_name``: Spanner database ID (default: ``emulator-test-database``).
* ``xdist_spanner_isolation_level``: ``"database"`` (default, per-worker database in a shared emulator) or ``"server"`` (per-worker container).
* ``spanner_service``: Provides a running ``SpannerService`` instance.

Service API
-----------

.. automodule:: pytest_databases.docker.spanner
   :members:
   :undoc-members:
   :show-inheritance:
