MongoDB
=======

Integration with `MongoDB <https://www.mongodb.com/>`_, a NoSQL document-oriented database.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mongodb]

The ``mongodb`` extra is kept as a compatibility group. The fixture provides a running MongoDB service and validates
availability with MongoDB's bundled ``mongosh`` client. Install the MongoDB client library that your application
already uses (for example, `PyMongo <https://pymongo.readthedocs.io/>`_).

Usage Example
-------------

.. code-block:: python

    import pymongo
    from pytest_databases.docker.mongodb import MongoDBService

    pytest_plugins = ["pytest_databases.docker.mongodb"]

    def test_mongodb_service(mongodb_service: MongoDBService) -> None:
        client = pymongo.MongoClient(
            host=mongodb_service.host,
            port=mongodb_service.port,
            username=mongodb_service.username,
            password=mongodb_service.password,
        )
        try:
            client.admin.command("ping")
            db = client[mongodb_service.database]
            collection = db["mycollection"]
            collection.insert_one({"name": "test_document", "value": 1})
            result = collection.find_one({"name": "test_document"})
            assert result is not None
            assert result["value"] == 1
        finally:
            client.close()

Available Fixtures
------------------

* ``mongodb_service``: A fixture that provides a MongoDB service, giving access to connection details like host, port, username, password, and the worker-specific database name.
* ``mongodb_image``: A fixture that returns the Docker image name used for the MongoDB service (default: "mongo:latest"). You can override this fixture to use a different MongoDB version.

Service API
-----------

.. automodule:: pytest_databases.docker.mongodb
   :members: MongoDBService, _provide_mongodb_service
   :undoc-members:
   :show-inheritance:
