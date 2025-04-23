BigQuery
========

Integration with `Google BigQuery <https://cloud.google.com/bigquery>`_ using the `BigQuery Emulator <https://github.com/goccy/bigquery-emulator>`_

This integration uses the official `Google Cloud BigQuery Python Client <https://cloud.google.com/python/docs/reference/bigquery/latest>`_ for testing against the BigQuery Emulator. The emulator is a third-party project that provides a local development environment that mimics the behavior of BigQuery, allowing you to test your application without connecting to the actual service.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[bigquery]

Usage Example
-------------

.. code-block:: python

    import pytest
    from google.cloud import bigquery
    from pytest_databases.docker.bigquery import BigQueryService

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test(bigquery_service: BigQueryService) -> None:
        client = bigquery.Client(
            project=bigquery_service.project,
            client_options=bigquery_service.client_options,
            credentials=bigquery_service.credentials,
        )

        job = client.query(query="SELECT 1 as one")
        resp = list(job.result())
        assert resp[0].one == 1

    def test(bigquery_client: bigquery.Client) -> None:
        assert isinstance(bigquery_client, bigquery.Client)

Available Fixtures
------------------

* ``bigquery_image``: The Docker image to use for BigQuery.
* ``bigquery_service``: A fixture that provides a BigQuery service.
* ``bigquery_client``: A fixture that provides a BigQuery client.

Service API
-----------

.. automodule:: pytest_databases.docker.bigquery
   :members:
   :undoc-members:
   :show-inheritance:
