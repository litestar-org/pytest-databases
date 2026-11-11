MongoDB
=======

Integration with `MongoDB <https://www.mongodb.com/>`_, a NoSQL document-oriented database.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

The fixture provides a running MongoDB service and validates
availability with MongoDB's bundled ``mongosh`` client. Install the MongoDB client library that your application
already uses (for example, `PyMongo <https://pymongo.readthedocs.io/>`_).

Usage Example
-------------

.. code-block:: python

    import pymongo
    from pytest_databases.docker.mongodb import MongoDBService

    pytest_plugins = ["pytest_databases.docker.mongodb"]

    def test_mongodb_service(mongodb_service: MongoDBService) -> None:
        client = pymongo.MongoClient(mongodb_service.uri)
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

Replica Sets and Query Profiling
--------------------------------

Set ``MONGODB_REPLICA_SET`` (or override ``mongodb_replica_set`` to return a replica set name such as ``"rs0"``) to
start MongoDB as an initialized single-node replica set with an elected ``PRIMARY`` — generating an internal
``0400`` ``--keyFile`` automatically when authentication is enabled and adding ``replicaSet`` and
``directConnection=true`` to ``mongodb_service.uri`` for multi-document transactions, change streams,
``replSetGetStatus``, and ``local.oplog.rs`` tests. Set ``MONGODB_USER=""`` (or override ``mongodb_username`` to return
``None``) for unauthenticated containers.

:meth:`~pytest_databases.docker.mongodb.MongoDBService.exec_js` (:func:`~pytest_databases.docker.mongodb.exec_mongosh`)
executes JavaScript inside the container via ``mongosh``, and
:meth:`~pytest_databases.docker.mongodb.MongoDBService.set_profiling_level` configures ``system.profile``. Custom
fixtures calling :func:`~pytest_databases.docker.mongodb.provide_mongodb_service` can also pass ``command``, ``env``,
``init_js``, ``profiling_level``, and ``slow_ms``.

Available Fixtures
------------------

* ``mongodb_service``: Provides a :class:`~pytest_databases.docker.mongodb.MongoDBService` exposing ``uri``, ``host``,
  ``port``, ``username``, ``password``, ``database``, ``replica_set``, ``exec_js()``, and ``set_profiling_level()``.
* ``mongodb_image``: Docker image name used for the MongoDB service (default: ``"mongo:latest"``, env ``MONGODB_IMAGE``).
* ``mongodb_username``: Root username, or ``None`` when ``MONGODB_USER=""`` disables authentication (default:
  ``"mongo_user"``, env ``MONGODB_USER``).
* ``mongodb_password``: Root password (default: ``"mongo_password"``, env ``MONGODB_PASSWORD``).
* ``mongodb_database_name``: Base database name (default: ``"pytest_db"``, env ``MONGODB_DATABASE``;
  ``<mongodb_database_name>_<worker>`` under ``pytest-xdist`` ``"database"`` isolation).
* ``mongodb_port``: Optional pinned host TCP port (default: ``None``, env ``MONGODB_PORT``).
* ``mongodb_replica_set``: Optional single-node replica set name (default: ``None``, env ``MONGODB_REPLICA_SET``).
* ``xdist_mongodb_isolation_level``: Worker isolation mode: ``"database"`` (default) or ``"server"``.
* ``mongodb_connection`` and ``mongodb_database``: Deprecated ``pymongo`` client and database fixtures.

Service API
-----------

.. automodule:: pytest_databases.docker.mongodb
   :members:
   :undoc-members:
   :show-inheritance:
