Floci Cloud Emulators (GCP, OCI, AWS, Azure)
============================================

Integration with `Floci <https://github.com/floci-io/floci>`_ cloud service emulators for Amazon Web Services
(``floci/floci``), Microsoft Azure (``floci/floci-az``), Google Cloud Platform (``floci/floci-gcp``), and Oracle Cloud
Infrastructure (``floci/floci-oci``). Each image serves every emulated service of its cloud on one gateway port:

.. list-table::
   :header-rows: 1

   * - Cloud
     - Fixture
     - Default image
     - Container port
     - Health path
   * - AWS
     - ``floci_aws_service``
     - ``floci/floci:2.4.0``
     - ``4566``
     - ``/_floci/health`` (also ``/_localstack/health``)
   * - Azure
     - ``floci_az_service``
     - ``floci/floci-az:0.16.0``
     - ``4577``
     - ``/_floci/health`` (also ``/health``)
   * - GCP
     - ``floci_gcp_service``
     - ``floci/floci-gcp:0.12.0``
     - ``4588``
     - ``/_floci-gcp/health``
   * - OCI
     - ``floci_oci_service``
     - ``floci/floci-oci:0.6.0``
     - ``4599``
     - ``/_floci-oci/health``

The fixtures are clientless: readiness probes and the bucket helpers use the standard library, so
``google-cloud-storage``, ``oci``, ``boto3``, and ``azure-storage-blob`` are not required.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Google Cloud Platform (``floci_gcp_service``)
---------------------------------------------

Emulates Cloud Storage, Pub/Sub, Firestore, Bigtable, Cloud KMS, Secret Manager, and more. By default,
``floci_gcp_compat_proxy`` (``FLOCI_GCP_COMPAT_PROXY``, default ``True``) places a stdlib loopback compatibility proxy
in front of Floci GCP that injects missing ``ETag`` and RFC-2822 ``Last-Modified`` headers and
``<ListBucketResult><Contents>`` XML fields, translates XML ``PUT`` with ``x-goog-copy-source`` into JSON ``copyTo``
responses (``<CopyObjectResult>``), and serves XML ``HEAD`` requests via upstream ``GET`` with accurate
``Content-Length`` and an empty body so ``obstore`` (``GCSStore``), ``gcsfs``, and ``google-cloud-storage`` work out of
the box. Set ``FLOCI_GCP_COMPAT_PROXY=0`` to target the raw container port directly:

.. code-block:: python

   from pytest_databases.docker.floci import FlociGCPService

   pytest_plugins = ["pytest_databases.docker.floci"]


   def test_gcs_bucket(floci_gcp_service: FlociGCPService) -> None:
       bucket = floci_gcp_service.ensure_bucket(f"{floci_gcp_service.resource_prefix}uploads")
       assert bucket["name"].endswith("uploads")
       assert floci_gcp_service.storage_emulator_host == floci_gcp_service.endpoint_url

Oracle Cloud Infrastructure (``floci_oci_service``)
---------------------------------------------------

Emulates Object Storage, Queue, Vault, Secrets, Streaming, and more. Floci OCI accepts unsigned requests and attributes
them to its local tenancy, so ``floci_oci_namespace`` defaults to that tenancy's namespace ``floci-local`` and
``floci_oci_compartment_id`` to its root compartment OCID:

.. code-block:: python

   from pytest_databases.docker.floci import FlociOCIService

   pytest_plugins = ["pytest_databases.docker.floci"]


   def test_oci_bucket(floci_oci_service: FlociOCIService) -> None:
       bucket = floci_oci_service.ensure_bucket(f"{floci_oci_service.resource_prefix}exports")
       assert bucket["name"].endswith("exports")

Amazon Web Services (``floci_aws_service``)
-------------------------------------------

Tokenless AWS emulator (S3, SQS, SNS, DynamoDB, Secrets Manager, KMS, Lambda, and more). Point an SDK at
``floci_aws_service.endpoint_url`` with ``region``, ``access_key``, and ``secret_key``. Use
:meth:`~pytest_databases.docker.floci.FlociAWSService.ensure_bucket` (returns ``None``, raising ``RuntimeError`` on
failure) or top-level :func:`pytest_databases.create_s3_bucket` (returning ``bool``):

.. code-block:: python

   from pytest_databases import create_s3_bucket
   from pytest_databases.docker.floci import FlociAWSService

   pytest_plugins = ["pytest_databases.docker.floci"]


   def test_aws_buckets(floci_aws_service: FlociAWSService) -> None:
       floci_aws_service.ensure_bucket(f"{floci_aws_service.resource_prefix}app-uploads")
       created = create_s3_bucket(
           floci_aws_service.endpoint_url,
           f"{floci_aws_service.resource_prefix}secondary",
           access_key=floci_aws_service.access_key,
           secret_key=floci_aws_service.secret_key,
           region=floci_aws_service.region,
       )
       assert created is True

Microsoft Azure (``floci_az_service``)
--------------------------------------

Azure emulator (Blob Storage, Queue Storage, Service Bus, Key Vault, Cosmos DB, and more). Blob Storage is path-style
at ``floci_az_service.blob_endpoint`` (``<endpoint_url>/<account_name>``); any account name and key are accepted.

Isolation
---------

With the default ``xdist_floci_isolation_level`` (``database``) all pytest-xdist workers share one container per
cloud; prefix resource names with ``resource_prefix`` (``pytest-databases-<worker>-``) to keep them apart. With
``server`` each worker starts its own container named ``floci_<cloud>_<worker>``.

Available Fixtures
------------------

* ``floci_gcp_image``, ``floci_gcp_project``, ``floci_gcp_compat_proxy`` (default ``True``, env ``FLOCI_GCP_COMPAT_PROXY``), ``floci_gcp_service``
* ``floci_oci_image``, ``floci_oci_namespace``, ``floci_oci_region``, ``floci_oci_compartment_id``,
  ``floci_oci_service``
* ``floci_aws_image``, ``floci_aws_region``, ``floci_aws_access_key``, ``floci_aws_secret_key``,
  ``floci_aws_service``
* ``floci_az_image``, ``floci_az_account_name``, ``floci_az_account_key``, ``floci_az_service``
* ``floci_resource_prefix`` and ``xdist_floci_isolation_level``

Each image fixture reads an environment variable (``FLOCI_AWS_IMAGE``, ``FLOCI_AZ_IMAGE``, ``FLOCI_GCP_IMAGE``,
``FLOCI_OCI_IMAGE``), as do the other settings (``FLOCI_GCP_PROJECT``, ``FLOCI_OCI_NAMESPACE``,
``FLOCI_RESOURCE_PREFIX``, ...).

Service API
-----------

.. automodule:: pytest_databases.docker.floci
   :members:
   :undoc-members:
   :show-inheritance:
