LocalStack
==========

Integration with `LocalStack <https://www.localstack.cloud/>`_, an AWS service
emulator. The fixture exposes the LocalStack gateway and can run AWS commands
inside the service container. No Python AWS SDK or host-side AWS CLI is
required.

Installation
------------

LocalStack support is included in the base package:

.. code-block:: bash

   pip install pytest-databases

Image and Authentication
------------------------

The default image is ``localstack/localstack:4.14.0``, the final tokenless
Community release. This preserves an offline default that needs neither a
LocalStack account nor cloud credentials. Current LocalStack releases require
an auth token. To opt into one, set both ``LOCALSTACK_IMAGE`` and
``LOCALSTACK_AUTH_TOKEN``.

The image must provide ``awslocal`` or ``aws`` and ``curl``. The standard
LocalStack image includes them. The fixture uses those in-container tools for
readiness and AWS operations, and does not mount a container-engine socket.

Configuration
-------------

* ``LOCALSTACK_IMAGE``: Image override (default: ``localstack/localstack:4.14.0``).
* ``LOCALSTACK_AUTH_TOKEN``: Optional token for images that require one.
* ``LOCALSTACK_REGION``: AWS region (default: ``us-east-1``).
* ``LOCALSTACK_ACCESS_KEY``: Test access key (default: ``test``).
* ``LOCALSTACK_SECRET_KEY``: Test secret key (default: ``test``).
* ``LOCALSTACK_SERVICES``: Optional comma-separated service allowlist. Omitting
  it leaves LocalStack's normal service set available.
* ``LOCALSTACK_RESOURCE_PREFIX``: Resource-name prefix override. By default,
  each xdist worker receives a distinct prefix.

Usage Example
-------------

``exec_aws_cli()`` executes in the LocalStack container. This example creates,
sends to, receives from, and deletes an SQS queue without importing an AWS
client library:

.. code-block:: python

   import json

   from pytest_databases.docker.localstack import LocalStackService

   pytest_plugins = ["pytest_databases.docker.localstack"]


   def test_sqs(localstack_service: LocalStackService) -> None:
       queue_name = f"{localstack_service.resource_prefix}messages"
       created = json.loads(
           localstack_service.exec_aws_cli(
               "sqs", "create-queue", "--queue-name", queue_name, "--output", "json"
           )
       )
       queue_url = created["QueueUrl"]
       localstack_service.exec_aws_cli(
           "sqs", "send-message", "--queue-url", queue_url, "--message-body", "hello"
       )
       received = json.loads(
           localstack_service.exec_aws_cli(
               "sqs", "receive-message", "--queue-url", queue_url, "--output", "json"
           )
       )
       message = received["Messages"][0]
       assert message["Body"] == "hello"
       localstack_service.exec_aws_cli(
           "sqs",
           "delete-message",
           "--queue-url",
           queue_url,
           "--receipt-handle",
           message["ReceiptHandle"],
       )
       localstack_service.exec_aws_cli("sqs", "delete-queue", "--queue-url", queue_url)

Available Fixtures
------------------

* ``localstack_image``
* ``localstack_auth_token``
* ``localstack_region``
* ``localstack_access_key``
* ``localstack_secret_key``
* ``localstack_services``
* ``localstack_resource_prefix``
* ``xdist_localstack_isolation_level``
* ``localstack_service``

The default xdist isolation level is ``database``: workers share a server and
use unique resource prefixes. Override ``xdist_localstack_isolation_level`` to
``server`` to start one transient LocalStack container per worker.

Service API
-----------

.. automodule:: pytest_databases.docker.localstack
   :members:
   :undoc-members:
   :show-inheritance:
