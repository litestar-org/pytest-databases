MiniStack and LocalStack
=========================

Integration with `MiniStack <https://github.com/ministackorg/ministack>`_ and
`LocalStack <https://www.localstack.cloud/>`_, AWS service emulators. The fixture
exposes the AWS gateway on port 4566 and runs AWS commands inside the service container.
No Python AWS SDK or host-side AWS CLI is required.

Installation
------------

AWS service emulator support is included in the base package:

.. code-block:: bash

   pip install pytest-databases

Image and Authentication
------------------------

The default image is ``ministackorg/ministack:latest``, an actively maintained,
MIT-licensed drop-in emulator that requires zero auth tokens and runs offline without
cloud account credentials.

If you require LocalStack commercial features or enterprise extensions, you can opt
into a custom LocalStack image by setting ``LOCALSTACK_IMAGE`` (and optionally
``LOCALSTACK_AUTH_TOKEN``):

.. code-block:: bash

   export LOCALSTACK_IMAGE=localstack/localstack:latest
   export LOCALSTACK_AUTH_TOKEN=your-token

The container provides ``awslocal`` or ``aws`` and health check endpoints. The
fixture uses those in-container tools for readiness and AWS operations without mounting
a container-engine socket.

Configuration
-------------

* ``MINISTACK_IMAGE`` / ``LOCALSTACK_IMAGE``: Image override (default: ``ministackorg/ministack:latest``).
* ``MINISTACK_AUTH_TOKEN`` / ``LOCALSTACK_AUTH_TOKEN``: Optional token for commercial images.
* ``MINISTACK_REGION`` / ``LOCALSTACK_REGION``: AWS region (default: ``us-east-1``).
* ``MINISTACK_ACCESS_KEY`` / ``LOCALSTACK_ACCESS_KEY``: Test access key (default: ``test``).
* ``MINISTACK_SECRET_KEY`` / ``LOCALSTACK_SECRET_KEY``: Test secret key (default: ``test``).
* ``MINISTACK_SERVICES`` / ``LOCALSTACK_SERVICES``: Optional comma-separated service allowlist.
* ``MINISTACK_RESOURCE_PREFIX`` / ``LOCALSTACK_RESOURCE_PREFIX``: Resource-name prefix override.
  By default, each xdist worker receives a distinct prefix.

Usage Example
-------------

``exec_aws_cli()`` executes in the emulator container. This example creates,
sends to, receives from, and deletes an SQS queue without importing an AWS
client library:

.. code-block:: python

   import json

   from pytest_databases.docker.localstack import MiniStackService

   pytest_plugins = ["pytest_databases.docker.localstack"]


   def test_sqs(ministack_service: MiniStackService) -> None:
       queue_name = f"{ministack_service.resource_prefix}messages"
       created = json.loads(
           ministack_service.exec_aws_cli(
               "sqs", "create-queue", "--queue-name", queue_name, "--output", "json"
           )
       )
       queue_url = created["QueueUrl"]
       ministack_service.exec_aws_cli(
           "sqs", "send-message", "--queue-url", queue_url, "--message-body", "hello"
       )
       received = json.loads(
           ministack_service.exec_aws_cli(
               "sqs", "receive-message", "--queue-url", queue_url, "--output", "json"
           )
       )
       message = received["Messages"][0]
       assert message["Body"] == "hello"
       ministack_service.exec_aws_cli(
           "sqs",
           "delete-message",
           "--queue-url",
           queue_url,
           "--receipt-handle",
           message["ReceiptHandle"],
       )
       ministack_service.exec_aws_cli("sqs", "delete-queue", "--queue-url", queue_url)

Available Fixtures
------------------

* ``ministack_image`` / ``localstack_image``
* ``ministack_auth_token`` / ``localstack_auth_token``
* ``ministack_region`` / ``localstack_region``
* ``ministack_access_key`` / ``localstack_access_key``
* ``ministack_secret_key`` / ``localstack_secret_key``
* ``ministack_services`` / ``localstack_services``
* ``ministack_resource_prefix`` / ``localstack_resource_prefix``
* ``xdist_ministack_isolation_level`` / ``xdist_localstack_isolation_level``
* ``ministack_service`` / ``localstack_service``

The default xdist isolation level is ``database``: workers share a server and
use unique resource prefixes. Override to ``server`` to start one transient container
per worker.

Service API
-----------

.. automodule:: pytest_databases.docker.localstack
   :members:
   :undoc-members:
   :show-inheritance:
