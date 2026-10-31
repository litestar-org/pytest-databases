Configuration
=============

``pytest-databases`` reads its settings from pytest options, ``pyproject.toml`` / ``pytest.ini`` settings, and
environment variables. They cover the container runtime (Docker or Podman), container ownership and teardown, and
``pytest-xdist`` isolation.

Container Runtime
~~~~~~~~~~~~~~~~~

Containers run on Docker or Podman. In ``auto`` mode Docker is preferred when both are reachable.

* ``--container-runtime`` (``auto``, ``docker`` or ``podman``): runtime for this run. Takes precedence over the
  ``container_runtime`` ini setting.
* ``container_runtime`` (ini): default runtime when ``--container-runtime`` is not given.
* ``PYTEST_DATABASES_CONTAINER_RUNTIME`` (falls back to ``CONTAINER_RUNTIME``): runtime when neither the option nor
  the ini setting is set. The default is ``auto``.
* ``PYTEST_DATABASES_CONTAINER_RUNTIME_ENDPOINT``, ``DOCKER_HOST`` or ``CONTAINER_HOST`` (checked in that order):
  explicit daemon endpoint, for example ``unix:///run/user/1000/podman/podman.sock``. ``CONTAINER_HOST`` marks the
  endpoint as Podman.

Without an explicit endpoint, the runtime is resolved from the current Docker context, the default Docker socket,
Podman connection files, and the rootless and rootful Podman sockets.

.. code-block:: toml

   [tool.pytest.ini_options]
   container_runtime = "podman"

Podman
------

Start the Podman API socket before running the tests. ``auto`` mode finds the rootless socket
(``$XDG_RUNTIME_DIR/podman/podman.sock``) and the rootful socket (``/run/podman/podman.sock``):

.. code-block:: bash

   systemctl --user enable --now podman.socket
   pytest --container-runtime=podman

The ``container_runtime``, ``container_client`` and ``container_service`` fixtures expose the resolved runtime, a
Docker SDK client connected to it, and the session's container manager. ``docker_client`` and ``docker_service``
remain as aliases.

Container Ownership and Teardown
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each session derives an owner ID from the pytest root path. Containers are named
``pytest_databases_<service>_<owner>`` and carry the labels ``pytest_databases``, ``pytest_databases.owner`` (the owner
ID) and ``pytest_databases.service``. At session start and end, ``pytest-databases`` only removes containers whose
``pytest_databases.owner`` label matches the current session, so separate checkouts never stop each other's
containers, and containers left behind by a crashed run of the same checkout are removed on the next run.

* ``PYTEST_DATABASES_NAMESPACE``: suffix appended to the owner ID. Set it to run two sessions from the same checkout
  at the same time without sharing containers.
* ``--keep-containers`` or ``PYTEST_DATABASES_KEEP_CONTAINERS`` (``1``, ``true``, ``yes``, ``on``, ...): leave the
  containers running after the session. The next session with the same owner ID reuses them.

``pytest_databases.stop_owned_containers(client, owner_id)`` and ``pytest_databases.stop_all_containers(client)``
remove containers by hand; the latter removes every container labelled ``pytest_databases`` regardless of owner.

Parallel Execution (``pytest-xdist``) Isolation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Services expose a session-scoped ``xdist_<backend>_isolation_level`` fixture that returns ``"database"`` or
``"server"``:

* ``"database"`` (the default): workers share one container and each worker gets its own database, schema, bucket,
  virtual host, or resource prefix, depending on the service.
* ``"server"``: each worker starts its own transient container.

SAP SQL Anywhere is the exception: it supports only ``"server"``, which is also its default.

Override the fixture in ``conftest.py`` to change the level:

.. code-block:: python

   import pytest
   from pytest_databases.types import XdistIsolationLevel

   @pytest.fixture(scope="session")
   def xdist_postgres_isolation_level() -> XdistIsolationLevel:
       return "server"

Accessing Configuration in Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The effective configuration values are available as attributes on the service fixture objects:

.. code-block:: python

   from pytest_databases.docker.postgres import PostgresService

   def test_postgres_config_access(postgres_service: PostgresService) -> None:
       assert postgres_service.user == "postgres"
       assert postgres_service.password == "super-secret"
       assert isinstance(postgres_service.port, int)
       assert postgres_service.port > 0
