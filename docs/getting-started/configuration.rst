Configuration
=============

``pytest-databases`` supports configuring the container runtime (Docker or Podman), container daemon endpoints, deterministic session ownership, ``pytest-xdist`` isolation modes, and container teardown behavior via pytest options, ``pyproject.toml`` / ``pytest.ini`` settings, and environment variables.

Container Runtime & Session Ownership
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can select between Docker and Podman or let ``pytest-databases`` auto-detect the available container runtime:

* ``--container-runtime`` / ``container_runtime`` (ini) / ``PYTEST_DATABASES_CONTAINER_RUNTIME``: Container runtime engine to use (``auto``, ``docker``, or ``podman``; default: ``auto``).
* ``--keep-containers`` / ``keep_containers`` (ini) / ``PYTEST_DATABASES_KEEP_CONTAINERS``: Retain containers after session teardown instead of removing them (default: ``False``).
* ``PYTEST_DATABASES_CONTAINER_RUNTIME_ENDPOINT`` / ``DOCKER_HOST`` / ``CONTAINER_HOST``: Explicit container daemon socket URI (for example ``unix:///run/user/1000/podman/podman.sock``).
* ``PYTEST_DATABASES_NAMESPACE``: Optional namespace combined with the repository root path to derive a deterministic ``pytest-databases.owner-id`` label so concurrent checkouts do not collide while crashed sessions are cleaned up automatically on the next run.

Example ``pyproject.toml`` configuration:

.. code-block:: toml

   [tool.pytest.ini_options]
   container_runtime = "auto"
   keep_containers = false

Parallel Execution (``pytest-xdist``) Isolation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Services that support multiple logical databases, schemas, virtual hosts, or resource prefixes expose a session-scoped ``xdist_<backend>_isolation_level`` fixture returning ``"database"`` (default, sharing a single container across workers) or ``"server"`` (starting a dedicated transient container per worker).

.. code-block:: python

   import pytest
   from pytest_databases.types import XdistIsolationLevel

   @pytest.fixture(scope="session")
   def xdist_postgres_isolation_level() -> XdistIsolationLevel:
       return "database"

Accessing Configuration in Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The effective configuration values are available as attributes on the service fixture objects:

.. code-block:: python

   from pytest_databases.docker.postgres import PostgresService

   def test_postgres_config_access(postgres_service: PostgresService) -> None:
       assert postgres_service.user == "postgres"
       assert postgres_service.password == "super-secret"
       assert postgres_service.database.startswith("pytest_databases")
       assert isinstance(postgres_service.port, int)
       assert postgres_service.port > 0
