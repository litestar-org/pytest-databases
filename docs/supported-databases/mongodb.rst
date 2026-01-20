MongoDB
=======

Integration with `MongoDB <https://www.mongodb.com/>`_, a NoSQL document-oriented database.

This integration uses the official `PyMongo <https://pymongo.readthedocs.io/>`_ driver to interact with MongoDB.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mongodb]


Usage Example
-------------

.. code-block:: python

    import pytest
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
        # Ping the server to ensure connection
        client.admin.command("ping")
        client.close()

    def test_mongodb_connection(mongodb_connection: pymongo.MongoClient) -> None:
        # mongodb_connection is an instance of pymongo.MongoClient
        # You can use it to interact with the database
        db = mongodb_connection["mydatabase"]
        collection = db["mycollection"]
        collection.insert_one({"name": "test_document", "value": 1})
        result = collection.find_one({"name": "test_document"})
        assert result is not None
        assert result["value"] == 1
        # Clean up (optional, depending on your test needs)
        collection.delete_one({"name": "test_document"})
        mongodb_connection.close()

    def test_mongodb_database(mongodb_database: pymongo.database.Database) -> None:
        # mongodb_database is an instance of pymongo.database.Database
        # This fixture provides a database that is unique per test function if xdist is used
        # and xdist_mongodb_isolation_level is "database" (the default).
        collection = mongodb_database["mycollection"]
        collection.insert_one({"name": "another_document", "value": 2})
        result = collection.find_one({"name": "another_document"})
        assert result is not None
        assert result["value"] == 2
        # No need to close the database object explicitly, the connection is managed by mongodb_connection

Available Fixtures
------------------

* ``mongodb_service``: A fixture that provides a MongoDB service, giving access to connection details like host, port, username, and password.
* ``mongodb_connection``: A fixture that provides a ``pymongo.MongoClient`` instance connected to the MongoDB service.
* ``mongodb_database``: A fixture that provides a ``pymongo.database.Database`` instance.
* ``mongodb_image``: A fixture that returns the Docker image name used for the MongoDB service (default: "mongo:latest"). You can override this fixture to use a different MongoDB version.

Service API
-----------

.. automodule:: pytest_databases.docker.mongodb
   :members: MongoDBService, _provide_mongodb_service
   :undoc-members:
   :show-inheritance:
