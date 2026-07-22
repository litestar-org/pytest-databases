Google Pub/Sub
==============

Integration with `Google Cloud Pub/Sub <https://cloud.google.com/pubsub>`_ using Google's official
`Pub/Sub emulator <https://cloud.google.com/pubsub/docs/emulator>`_. The fixture starts the version-pinned Google Cloud
CLI emulator image and validates it with the ``gcloud`` tooling already present in that image. The package does not
depend on ``google-cloud-pubsub`` or mutate Google credential environment variables.

Installation
------------

Install the base package:

.. code-block:: bash

   pip install pytest-databases

Install the Pub/Sub client used by your application separately, if it needs one.

Usage
-----

Enable the plugin and pass the service metadata to your application. Standard Google clients recognize
``PUBSUB_EMULATOR_HOST``; set it in your own fixture or application configuration so the parent test process remains
under your control.

.. code-block:: python

   import pytest

   from pytest_databases.docker.pubsub import PubSubService

   pytest_plugins = ["pytest_databases.docker.pubsub"]


   @pytest.fixture
   def pubsub_environment(pubsub_service: PubSubService, monkeypatch: pytest.MonkeyPatch) -> PubSubService:
       monkeypatch.setenv("PUBSUB_EMULATOR_HOST", pubsub_service.emulator_host)
       monkeypatch.setenv("PUBSUB_PROJECT_ID", pubsub_service.project)
       return pubsub_service


   def test_publish_event(pubsub_environment: PubSubService) -> None:
       assert pubsub_environment.emulator_host == (
           f"{pubsub_environment.host}:{pubsub_environment.port}"
       )
       # Call application code configured by pubsub_environment here.

The service fixture waits for both the emulator's documented ``Server started`` log and the mapped TCP endpoint. Before
yielding, an ephemeral sidecar from the same official image creates a topic and subscription, publishes a payload, pulls
and acknowledges it, and removes the smoke resources. No host-side Google client or credentials are involved.

Available fixtures
------------------

* ``pubsub_image``: Google Cloud CLI ``577.0.0-emulators`` image. Override it to test a newer compatible release.
* ``pubsub_project``: ``pytest-databases`` outside xdist and a worker-suffixed project under xdist.
* ``xdist_pubsub_isolation_level``: ``database`` by default; override with ``server`` for one container per worker.
* ``pubsub_service``: :class:`~pytest_databases.docker.pubsub.PubSubService` containing ``host``, ``port``, ``project``,
  ``emulator_host``, and the underlying container.

Parallel isolation
------------------

The default ``database`` isolation shares one emulator container and assigns each xdist worker a separate project ID.
The emulator namespaces resources by project, so workers may use the same topic and subscription names. Override the
isolation fixture when a test needs a separate emulator process:

.. code-block:: python

   import pytest


   @pytest.fixture(scope="session")
   def xdist_pubsub_isolation_level() -> str:
       return "server"

Limitations
-----------

The emulator is intended for local development and can differ from the production service. IAM integration, ACL checks,
and some production features are not implemented. Data is ephemeral, and tests should not use the emulator to validate
credentials, permissions, quotas, or production delivery guarantees.

Service API
-----------

.. automodule:: pytest_databases.docker.pubsub
   :members:
   :undoc-members:
   :show-inheritance:
