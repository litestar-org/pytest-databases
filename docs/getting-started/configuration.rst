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
containers. Each active session also holds an advisory OS file lease under its owner ID: if two local ``pytest``
processes run against the same checkout at the same time, shared containers remain running until the final active
session exits, while stale leases from crashed processes or processes terminated with ``SIGKILL`` are released by the
kernel and cleaned up on the next run.

* ``PYTEST_DATABASES_NAMESPACE``: suffix appended to the owner ID. Set it to run two sessions from the same checkout
  at the same time without sharing containers.
* ``--keep-containers`` or ``PYTEST_DATABASES_KEEP_CONTAINERS`` (``1``, ``true``, ``yes``, ``on``, ...): leave the
  containers running after the session. The next session with the same owner ID reuses them.

``pytest_databases.has_active_owner_sessions(owner_id)`` inspects whether another live session currently holds a lease
for ``owner_id``. ``pytest_databases.stop_owned_containers(client, owner_id)`` and
``pytest_databases.stop_all_containers(client)`` remove containers by hand; the latter removes every container labelled
``pytest_databases`` regardless of owner.

Custom Container Options and File Transfers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``container_service`` (aliased as ``docker_service``) exposes ``temp_dir`` (:attr:`~pytest_databases._service.ContainerService.temp_dir`), a session-scoped temporary :class:`pathlib.Path` for cross-worker ``filelock.FileLock`` coordination and session state files.

Custom fixtures calling ``container_service.run(...)`` can pass ``user``, ``tmpfs``, ``extra_hosts``, ``volumes``,
``shm_size``, ``mem_limit``, ``entrypoint``, ``command``, ``privileged``, ``ipc_mode``, ``cap_add``, ``devices`` and
``hostname`` directly to the container runtime. When ``exec_after_start`` is set on a shared container, it runs once
per container under a cross-worker file lock and raises ``RuntimeError`` if the command exits with a non-zero status.

Every container-backed service inherits from :class:`~pytest_databases.types.ServiceContainer`, which exposes stdlib
tar-archive transfer and command helpers without requiring ``docker cp`` or host client CLIs:

* ``service.copy_to(source, destination_dir, *, arcname=None, mode=None, uid=None, gid=None)``
  (:func:`~pytest_databases.types.copy_to_container`): upload a host file or directory into the running container,
  creating missing parent directories automatically.
* ``service.copy_from(source, destination, *, strip_components=False)``
  (:func:`~pytest_databases.types.copy_from_container`): extract a file or directory from the container into a host
  directory while rejecting path traversal, special device entries, and escaping links.
* ``service.exec_command(command, *, user=None, workdir=None, env=None)``
  (:func:`~pytest_databases.types.exec_container_command`): execute a command inside the container and return
  ``(exit_code, output_bytes)``.

PostgreSQL Backend Selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Suites targeting ``postgres_any_service`` (:class:`~pytest_databases.PostgresServiceProtocol`) can switch seamlessly
between containerized PostgreSQL (``"docker"``) and local embedded binaries (``"embedded"``):

* ``--postgres-backend`` (``docker`` or ``embedded``): CLI option with highest precedence.
* ``postgres_backend`` (ini): ``[tool.pytest.ini_options]`` setting used when ``--postgres-backend`` is omitted.
* ``PYTEST_DATABASES_POSTGRES_BACKEND``: environment variable fallback before defaulting to ``"docker"``.

``resolve_postgres_backend(config)`` resolves the active :data:`~pytest_databases.PostgresBackend` and raises
``pytest.UsageError`` for unsupported values. Selecting ``"embedded"`` resolves ``postgres_any_service`` directly via
embedded PostgreSQL without probing Docker or Podman.

Proxy-Free Readiness Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``pytest_databases.send_http_request``, ``pytest_databases.helpers.http_request(..., ssl_context=...)``, and
``pytest_databases.create_s3_bucket(..., timeout=10.0, ssl_context=None)`` (also exported from
``pytest_databases.helpers``) use Python's standard library with ambient ``HTTP_PROXY``, ``HTTPS_PROXY``, and
``ALL_PROXY`` variables bypassed so local container and emulator probes never route through corporate proxies.

Parallel Execution (``pytest-xdist``) Isolation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Services expose a session-scoped ``xdist_<backend>_isolation_level`` fixture that returns ``"database"`` or
``"server"``:

* ``"database"`` (the default): workers share one container and each worker gets its own database, schema, bucket,
  virtual host, or resource prefix, depending on the service.
* ``"server"``: each worker starts its own transient container.
* ``"template"`` (PostgreSQL family only, typed as ``PostgresXdistIsolationLevel``): workers share one container; a
  template database is built once and each worker database is cloned from it with file-level template cloning
  (``CREATE DATABASE ... TEMPLATE``). See :doc:`../supported-databases/postgres`.

BigQuery defaults to ``"server"`` (creating transient per-worker containers under ``pytest-xdist``, with opt-in
``"database"`` isolation), while SAP SQL Anywhere supports only ``"server"``, which is also its default.

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
