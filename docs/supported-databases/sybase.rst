Sybase ASE
==========

Integration with `SAP Sybase Adaptive Server Enterprise (ASE) <https://www.sap.com/products/technology-platform/sybase-ase.html>`_.

Installation
------------

.. code-block:: bash

   pip install pytest-databases

Install ``pymssql`` (compiled with FreeTDS TDS 5.0 support) in your application if your tests connect from the host.
The service fixtures validate container readiness using host TCP socket probing and in-container ``isql`` CLI tools without requiring driver packages in the base installation.

Usage Example
-------------

.. code-block:: python

   import pymssql
   from pytest_databases.docker.sybase import SybaseService

   pytest_plugins = ["pytest_databases.docker.sybase"]


   def test_sybase_connection(sybase_service: SybaseService) -> None:
       conn = pymssql.connect(
           server=sybase_service.host,
           port=sybase_service.port,
           user=sybase_service.user,
           password=sybase_service.password,
           database=sybase_service.database,
           autocommit=True,
       )
       with conn.cursor() as cur:
           cur.execute("SELECT 1")
           res = cur.fetchone()[0]
           assert res == 1

Available Fixtures
------------------

* ``sybase_image``: Docker image tag for SAP Sybase ASE (default: ``datagrip/sybase:16.0``).
* ``sybase_user``: Login user for the Sybase ASE instance (default: ``sa``).
* ``sybase_password``: Login password for the Sybase ASE instance (default: ``myPassword``).
* ``sybase_database``: Initial database to connect to (default: ``master``).
* ``sybase_startup_timeout``: Timeout in seconds for container startup (default: ``120``).
* ``xdist_sybase_isolation_level``: Worker isolation mode (default: ``database``).
* ``sybase_service``: Provides a running Sybase ASE service container.

Storage & Filesystem Notes (OverlayFS / 4Kn Direct I/O)
-------------------------------------------------------

On Linux hosts running Docker on ``overlayfs`` backed by 4Kn or non-512e block storage, Sybase ASE may encounter disk I/O errors (``Msg 823``) during device allocation or database resize operations due to direct I/O alignment constraints. If you experience ``Msg 823`` on such hosts, mount a ``tmpfs`` volume or standard sector-emulated storage over ``/opt/sybase/data`` when configuring custom container runs, similar to configuring ``DB2_DIRECT_IO=OFF`` for IBM Db2 or ``filesystemio_options='NONE'`` for Oracle ADB-Free.

Service API
-----------

.. automodule:: pytest_databases.docker.sybase
   :members:
   :undoc-members:
   :show-inheritance:
