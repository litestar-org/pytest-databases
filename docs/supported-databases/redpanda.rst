Redpanda
========

Integration with `Redpanda <https://www.redpanda.com/>`_, a Kafka-compatible
streaming data platform. The fixture starts a single development broker and
does not install or import a Python Kafka client.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install the Kafka client used by your application separately if your tests need
one. The service fixture itself remains clientless and uses the image's ``rpk``
command for startup and health checks.

Docker Image
------------

The default is the pinned official image
``docker.redpanda.com/redpandadata/redpanda:v26.1.13``. The fixture works with
both Docker and Podman through the selected container runtime. See
:doc:`../getting-started/container-runtimes`.

Configuration
-------------

* ``REDPANDA_IMAGE``: image override (default:
  ``docker.redpanda.com/redpandadata/redpanda:v26.1.13``).
* ``REDPANDA_PORT``: optional fixed host port. By default the container runtime
  allocates a free port.
* ``xdist_redpanda_isolation_level``: xdist isolation level (default:
  ``database``).

Usage Example
-------------

``RedpandaService.bootstrap_servers`` is the host-reachable Kafka endpoint to
pass to your application's Kafka client. ``topic_prefix`` is unique to the
xdist worker when logical isolation is active.

The following smoke test stays clientless by running ``rpk`` in the service
container:

.. code-block:: python

   from pytest_databases.docker.redpanda import RedpandaService

   pytest_plugins = ["pytest_databases.docker.redpanda"]


   def test_redpanda(redpanda_service: RedpandaService) -> None:
       topic = f"{redpanda_service.topic_prefix}events"
       result = redpanda_service.container.exec_run(
           [
               "rpk",
               "topic",
               "create",
               topic,
               "-X",
               "brokers=127.0.0.1:9092",
           ]
       )
       assert result.exit_code == 0
       assert redpanda_service.bootstrap_servers == (
           f"{redpanda_service.host}:{redpanda_service.port}"
       )

Parallel Testing (xdist)
------------------------

The default ``database`` isolation reuses one broker and gives each worker a
topic prefix such as ``pytest_databases_gw0_``. Tests must apply
``redpanda_service.topic_prefix`` to every topic they create.

Override the fixture with ``"server"`` when each worker needs a separate
broker:

.. code-block:: python

   import pytest


   @pytest.fixture(scope="session")
   def xdist_redpanda_isolation_level():
       return "server"

Server isolation starts one transient container per worker and returns an empty
topic prefix.

Available Fixtures
------------------

* ``redpanda_image``: the Redpanda image reference.
* ``redpanda_port``: the optional fixed host port.
* ``redpanda_service``: a running broker with ``bootstrap_servers`` and
  ``topic_prefix`` metadata.
* ``xdist_redpanda_isolation_level``: ``database`` or ``server`` isolation.

.. note::

   This fixture intentionally exposes Redpanda by name. It does not provide a
   ``kafka_service`` alias or claim complete Apache Kafka compatibility.

Service API
-----------

.. automodule:: pytest_databases.docker.redpanda
   :members:
   :undoc-members:
   :show-inheritance:
