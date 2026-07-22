RabbitMQ
========

Integration with `RabbitMQ 4.3 <https://www.rabbitmq.com/docs>`_ using the official
``rabbitmq:4.3-management`` container image.

Installation
------------

Install ``pytest-databases`` and the AMQP client used by your application. The fixture itself does not install or
import an AMQP client:

.. code-block:: bash

   pip install pytest-databases pika

Readiness and the pytest-databases smoke tests use ``rabbitmq-diagnostics`` and ``rabbitmqadmin`` from inside the
container. Only the AMQP port is published; the management port remains internal to the test container.

Usage example
-------------

.. code-block:: python

   import pika

   from pytest_databases.docker.rabbitmq import RabbitMQService

   pytest_plugins = ["pytest_databases.docker.rabbitmq"]


   def test_publish(rabbitmq_service: RabbitMQService) -> None:
       connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_service.amqp_url))
       channel = connection.channel()
       channel.queue_declare(queue="example", durable=True)
       channel.basic_publish(exchange="", routing_key="example", body=b"message")
       method, _, body = channel.basic_get(queue="example", auto_ack=True)
       assert method is not None
       assert body == b"message"
       connection.close()

Available fixtures
------------------

* ``rabbitmq_image``: Container image, defaulting to ``rabbitmq:4.3-management``.
* ``rabbitmq_username`` and ``rabbitmq_password``: Non-guest test credentials.
* ``rabbitmq_vhost``: Worker-specific virtual host with default xdist isolation.
* ``rabbitmq_host`` and ``rabbitmq_port``: Published AMQP endpoint.
* ``rabbitmq_service``: ``RabbitMQService`` with host, port, container, credentials, virtual host, and ``amqp_url``.
* ``xdist_rabbitmq_isolation_level``: ``"database"`` for one virtual host per worker, or ``"server"`` for one broker
  per worker.

Service API
-----------

.. automodule:: pytest_databases.docker.rabbitmq
   :members:
   :undoc-members:
   :show-inheritance:
