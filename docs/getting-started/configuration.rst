Configuration
=============

``pytest-databases`` uses environment variables for configuration. This allows you to override default settings like Docker image tags, usernames, passwords, ports, and database names.

Common Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These variables apply globally to the container setup. See :doc:`container-runtimes` for Docker and Podman selection,
endpoint discovery, and troubleshooting.

*   ``SKIP_DOCKER_COMPOSE=True``: If set, skip trying to manage database containers via Docker Compose. Useful if you manage services externally. (Default: "False")
*   ``USE_LEGACY_DOCKER_COMPOSE=True``: If set, forces the use of the older ``docker-compose`` command instead of ``docker compose``. (Default: "False")
*   ``PYTEST_DATABASES_CONTAINER_RUNTIME``: Selects ``auto``, ``docker``, or ``podman``. (Default: ``auto``)
*   ``CONTAINER_HOST`` or ``DOCKER_HOST``: Specifies the Docker-compatible API endpoint. This is not the host name
    reported by database service fixtures.

Database-Specific Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some drivers have additional environment variables for configuration.

Please refer to the documentation for the specific database you are using under the :doc:`../supported-databases/index` section for a complete list of its configuration variables.

Accessing Configuration in Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The effective configuration values (whether defaults or overridden by environment variables) are available as attributes on the service fixture objects:

.. code-block:: python

   from pytest_databases.docker.postgres import PostgresService

   def test_postgres_config_access(postgres_service: PostgresService) -> None:
       # Access configuration values used by the running service
       print(f"Connecting to Postgres user: {postgres_service.user}")
       print(f"Using database: {postgres_service.database}")
       print(f"On host: {postgres_service.host}:{postgres_service.port}")

       # Example assertions (replace with your expected defaults or env overrides)
       assert postgres_service.user == "postgres"
       assert postgres_service.password == "super-secret"
       assert postgres_service.database == "pytest_databases"
       assert postgres_service.host == "127.0.0.1" # Or your DOCKER_HOST override
       assert isinstance(postgres_service.port, int)
       assert postgres_service.port > 0
