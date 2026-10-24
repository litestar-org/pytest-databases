BigQuery
========

Integration with `Google BigQuery <https://cloud.google.com/bigquery>`_ using the `BigQuery Emulator <https://github.com/goccy/bigquery-emulator>`_.

Installation
------------

The BigQuery emulator fixture validates readiness using Python stdlib HTTP requests against the emulator REST API, so no Google Cloud Python SDK dependency is required to start the service:

.. code-block:: bash

   pip install pytest-databases

Usage Example
-------------

.. code-block:: python

    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import bigquery
    from pytest_databases.docker.bigquery import BigQueryService

    pytest_plugins = ["pytest_databases.docker.bigquery"]


    def test_bigquery(bigquery_service: BigQueryService) -> None:
        client = bigquery.Client(
            project=bigquery_service.project,
            client_options=ClientOptions(api_endpoint=bigquery_service.endpoint),
            credentials=AnonymousCredentials(),
        )

        job = client.query(query="SELECT 1 as one")
        resp = list(job.result())
        assert resp[0].one == 1

Available Fixtures
------------------

* ``bigquery_image``: The Docker image to use for the BigQuery emulator.
* ``bigquery_service``: A fixture that provides a :class:`~pytest_databases.docker.bigquery.BigQueryService` instance.
* ``bigquery_client``: Deprecated fixture that provides a ``google.cloud.bigquery.Client``.

Service API
-----------

.. automodule:: pytest_databases.docker.bigquery
   :members:
   :undoc-members:
   :show-inheritance:
