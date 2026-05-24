Elasticsearch
=============

Integration with `Elasticsearch <https://www.elastic.co/elasticsearch/>`_ using the
`Elasticsearch Docker Images <https://www.docker.elastic.co/>`_.

Installation
------------

For Elasticsearch 7.x:

.. code-block:: bash

   pip install pytest-databases[elasticsearch7]

For Elasticsearch 8.x:

.. code-block:: bash

   pip install pytest-databases[elasticsearch8]

The ``elasticsearch7`` and ``elasticsearch8`` extras are kept as compatibility groups. The fixtures provide a running
Elasticsearch service and validate readiness with stdlib ``urllib.request`` against ``/_cluster/health``. Install the
Elasticsearch client that your application already uses.

Usage Example
-------------

For Elasticsearch 7.x:

.. code-block:: python

    from elasticsearch7 import Elasticsearch
    from pytest_databases.docker.elastic_search import ElasticsearchService

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def test_elasticsearch_7(elasticsearch_7_service: ElasticsearchService) -> None:
        with Elasticsearch(
            hosts=[
                {
                    "host": elasticsearch_7_service.host,
                    "port": elasticsearch_7_service.port,
                    "scheme": elasticsearch_7_service.scheme,
                }
            ],
            verify_certs=False,
            http_auth=(elasticsearch_7_service.user, elasticsearch_7_service.password),
        ) as client:
            info = client.info()
            assert info["version"]["number"] == "7.17.19"

For Elasticsearch 8.x:

.. code-block:: python

    from elasticsearch8 import Elasticsearch
    from pytest_databases.docker.elastic_search import ElasticsearchService

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def test_elasticsearch_8(elasticsearch_8_service: ElasticsearchService) -> None:
        with Elasticsearch(
            hosts=[
                {
                    "host": elasticsearch_8_service.host,
                    "port": elasticsearch_8_service.port,
                    "scheme": elasticsearch_8_service.scheme,
                }
            ],
            verify_certs=False,
            basic_auth=(elasticsearch_8_service.user, elasticsearch_8_service.password),
        ) as client:
            info = client.info()
            assert info["version"]["number"] == "8.13.0"

Available Fixtures
------------------

* ``elasticsearch_service_memory_limit``: The memory limit for the Elasticsearch service (default: ``500m``)
* ``elasticsearch_service``: A fixture that provides an Elasticsearch service (aliases ``elasticsearch_8_service``).

The following version-specific fixtures are also available:

* ``elasticsearch_7_service``: Elasticsearch 7.x
* ``elasticsearch_8_service``: Elasticsearch 8.x

Service API
-----------

.. automodule:: pytest_databases.docker.elastic_search
   :members:
   :undoc-members:
   :show-inheritance:
