BigQuery
========

Integration with `Google BigQuery <https://cloud.google.com/bigquery>`_ using the
`BigQuery Emulator <https://github.com/goccy/bigquery-emulator>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[bigquery]

The ``bigquery`` extra is kept as a compatibility group. Install the BigQuery client
that your application already uses.

Usage Example
-------------

.. code-block:: python

    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import bigquery

    from pytest_databases.docker.bigquery import BigQueryService

    pytest_plugins = ["pytest_databases.docker.bigquery"]


    def test(bigquery_service: BigQueryService) -> None:
        client = bigquery.Client(
            project=bigquery_service.project,
            client_options=ClientOptions(api_endpoint=bigquery_service.endpoint),
            credentials=AnonymousCredentials(),
        )

        job = client.query(query="SELECT 1 AS one")
        rows = list(job.result())
        assert rows[0].one == 1

Available Fixtures
------------------

* ``bigquery_image``: The Docker image to use for the BigQuery emulator.
* ``bigquery_service``: A fixture that provides a running BigQuery emulator service.

Service API
-----------

.. automodule:: pytest_databases.docker.bigquery
   :members:
   :undoc-members:
   :show-inheritance:
