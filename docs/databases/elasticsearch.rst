\
.. _db_elasticsearch:

Elasticsearch
=============

Integration with Elasticsearch.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[elasticsearch]

Docker Image
------------

`Elasticsearch Docker Images <https://www.docker.elastic.co/>`_

Configuration
-------------

* ``ELASTICSEARCH_IMAGE``: Docker image to use for Elasticsearch (default: "docker.elastic.co/elasticsearch/elasticsearch:8.11.1")
* ``XDIST_ELASTICSEARCH_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``ELASTICSEARCH_USER``: Username for Elasticsearch (default: "elastic")
* ``ELASTICSEARCH_PASSWORD``: Password for Elasticsearch (default: "changeme")
* ``ELASTICSEARCH_SCHEME``: Scheme for Elasticsearch (default: "http")
* ``ELASTICSEARCH_DATABASE``: Database name for Elasticsearch (default: "test")

API
---

.. automodule:: pytest_databases.docker.elastic_search
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
