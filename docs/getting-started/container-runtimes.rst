Container runtimes
==================

``pytest-databases`` supports Docker and Podman through the Docker-compatible HTTP API. The package keeps the existing
``docker`` Python SDK as its only container client; it does not add ``podman-py`` or database client dependencies.

Selecting a runtime
-------------------

Automatic selection prefers a reachable Docker engine, then tries Podman connections and the standard rootless and
rootful Podman sockets. Select an engine explicitly with an environment variable:

.. code-block:: console

   PYTEST_DATABASES_CONTAINER_RUNTIME=podman pytest
   PYTEST_DATABASES_CONTAINER_RUNTIME=docker pytest

You can also override the session fixture:

.. code-block:: python

   import pytest

   from pytest_databases import RuntimeType


   @pytest.fixture(scope="session")
   def container_runtime() -> RuntimeType:
       return RuntimeType.PODMAN

Explicit selection never falls back to the other engine. ``DOCKER_HOST`` or ``CONTAINER_HOST`` is authoritative when
set; the endpoint is probed and must identify itself as the requested engine.

Linux rootless Podman
---------------------

Enable the user socket before running tests:

.. code-block:: console

   systemctl --user enable --now podman.socket
   PYTEST_DATABASES_CONTAINER_RUNTIME=podman pytest

The standard ``$XDG_RUNTIME_DIR/podman/podman.sock`` location is discovered automatically. To be explicit:

.. code-block:: console

   export CONTAINER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
   export PYTEST_DATABASES_CONTAINER_RUNTIME=podman

Podman machine
--------------

Start the machine yourself and point ``CONTAINER_HOST`` at its forwarded Docker-compatible API socket:

.. code-block:: console

   podman machine start
   podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}'
   export CONTAINER_HOST="unix:///path/printed/by/podman.sock"
   export PYTEST_DATABASES_CONTAINER_RUNTIME=podman

Podman connection JSON files are also inspected. Local ``unix://``, ``tcp://``, and Docker environment TLS transports
work without another dependency. An ``ssh://`` connection requires Docker SDK SSH support, which this package does not
install; use the machine's forwarded local socket to keep the test environment clientless.

Compatibility names
-------------------

New code can request ``container_client`` and ``container_service`` or import ``ContainerService``. Existing
``docker_client``, ``docker_service``, and ``DockerService`` names remain aliases and use the selected engine.

Lifecycle and safety
--------------------

Each pytest invocation receives a random owner ID shared by its xdist workers. Managed containers have exact owner and
logical-service labels plus owner-namespaced container names, so concurrent pytest invocations cannot stop or reuse one
another's services. Container creation is serialized only around the daemon's create/start/port-allocation call to avoid
the `rootless dynamic-port race reported in issue 152 <https://github.com/litestar-org/pytest-databases/issues/152>`_.

The library never starts Docker, a Podman socket, or a Podman machine and never invokes ``sudo``. Normal teardown removes
only the current owner's containers. After a hard-killed pytest process, stale managed containers can be removed
explicitly:

.. code-block:: python

   from pytest_databases import cleanup_stale_containers

   cleanup_stale_containers()

When both engines are running, select which daemon to clean explicitly:

.. code-block:: python

   cleanup_stale_containers(runtime="podman")

Troubleshooting
---------------

Resolution errors list the attempted sources and sanitized endpoints. Check the following before retrying:

- the selected engine is running and its API socket is enabled;
- the current user can read and write the socket;
- ``CONTAINER_HOST`` or ``DOCKER_HOST`` does not point to the other engine;
- a remote TLS endpoint has the matching ``DOCKER_TLS_VERIFY`` and ``DOCKER_CERT_PATH`` values;
- Podman machine users selected the forwarded local API socket rather than an unsupported SSH-only URI.
