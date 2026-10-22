Floci Cloud Emulators (GCP, OCI, AWS, Azure)
============================================

Integration with `Floci <https://github.com/floci-io/floci>`_ lightweight,
single-port (``4566``) cloud service emulators for Google Cloud Platform
(``floci/floci-gcp``), Oracle Cloud Infrastructure (``floci/floci-oci``),
Amazon Web Services (``floci/floci``), and Microsoft Azure (``floci/floci-az``).

All Floci fixtures are 100% clientless: readiness probing and bucket creation
helpers use Python's standard library ``urllib.request`` against the container
HTTP gateway without requiring ``google-cloud-storage``, ``oci``, ``boto3``, or
``azure-storage-blob`` in the base package.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Google Cloud Platform (``floci_gcp_service`` / ``gcs_service``)
---------------------------------------------------------------

Emulates Google Cloud Storage (GCS), Pub/Sub, Firestore, Bigtable, Cloud KMS,
and Secret Manager on port ``4566``:

.. code-block:: python

   from pytest_databases.docker.floci import FlociGCPService

   pytest_plugins = ["pytest_databases.docker.floci"]


   def test_gcs_bucket(gcs_service: FlociGCPService) -> None:
       bucket = gcs_service.ensure_bucket(f"{gcs_service.resource_prefix}uploads")
       assert bucket["name"].endswith("uploads")
       assert gcs_service.storage_emulator_host == gcs_service.endpoint_url

Oracle Cloud Infrastructure (``floci_oci_service``)
---------------------------------------------------

Emulates OCI Object Storage, Queue, Vault, Secrets, NoSQL, and Streaming on port
``4566``:

.. code-block:: python

   from pytest_databases.docker.floci import FlociOCIService

   pytest_plugins = ["pytest_databases.docker.floci"]


   def test_oci_bucket(floci_oci_service: FlociOCIService) -> None:
       bucket = floci_oci_service.ensure_bucket(f"{floci_oci_service.resource_prefix}exports")
       assert bucket["name"].endswith("exports")

Amazon Web Services (``floci_aws_service`` / ``floci_service``)
---------------------------------------------------------------

Tokenless AWS service emulator (S3, SQS, SNS, DynamoDB, Secrets Manager, KMS,
Lambda) on port ``4566``.

Microsoft Azure (``floci_az_service``)
--------------------------------------

Unified Azure service emulator (Blob Storage, Queue Storage, Service Bus, Key
Vault, Cosmos DB) on port ``4566``.

Available Fixtures
------------------

* ``floci_gcp_image``, ``floci_gcp_project``, ``floci_gcp_service``, ``gcs_service``
* ``floci_oci_image``, ``floci_oci_namespace``, ``floci_oci_region``,
  ``floci_oci_compartment_id``, ``floci_oci_service``
* ``floci_aws_image``, ``floci_aws_region``, ``floci_aws_access_key``,
  ``floci_aws_secret_key``, ``floci_aws_service``, ``floci_service``
* ``floci_az_image``, ``floci_az_account_name``, ``floci_az_account_key``,
  ``floci_az_service``
* ``floci_resource_prefix`` and ``xdist_floci_isolation_level``

Service API
-----------

.. automodule:: pytest_databases.docker.floci
   :members:
   :undoc-members:
   :show-inheritance:
