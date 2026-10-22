Elasticsearch
=============

Integration with `Elasticsearch <https://www.elastic.co/elasticsearch/>`_ using the `Elasticsearch Docker Image <https://hub.docker.com/_/elasticsearch>`_

Installation
------------

.. code-block:: bash

   pip install pytest-databases[elasticsearch]

The ``elasticsearch`` extra is kept as a compatibility group. Install the
Elasticsearch client that your application already uses (for example ``elasticsearch``).

Usage Example
-------------

.. code-block:: python

    import json
    import urllib.request
    from pytest_databases.docker.elastic_search import ElasticsearchService

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def test_elasticsearch(elasticsearch_service: ElasticsearchService) -> None:
        url = f"{elasticsearch_service.scheme}://{elasticsearch_service.host}:{elasticsearch_service.port}/"
        with urllib.request.urlopen(url, timeout=5) as response:
            info = json.loads(response.read().decode("utf-8"))
        assert "version" in info

Available Fixtures
------------------

* ``elasticsearch_service_memory_limit``: Memory limit for the Elasticsearch container (default: ``1g``).
* ``elasticsearch_service``: Provides an Elasticsearch service (aliases ``elasticsearch_8_service``).
* ``elasticsearch_7_service``: Elasticsearch 7.x container service.
* ``elasticsearch_8_service``: Elasticsearch 8.x container service.

Service API
-----------

.. automodule:: pytest_databases.docker.elastic_search
   :members:
   :undoc-members:
   :show-inheritance:
