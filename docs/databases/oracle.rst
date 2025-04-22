\
.. _db_oracle:

Oracle
======

Integration with Oracle.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[oracle]

Docker Image
------------

`Oracle Database Docker Images <https://hub.docker.com/r/oracle/database/>`_

Configuration
-------------

* ``ORACLE_18C_IMAGE``: Docker image to use for Oracle 18c (default: "gvenzl/oracle-xe:18")
* ``ORACLE_23AI_IMAGE``: Docker image to use for Oracle 23c (default: "gvenzl/oracle-free:23")
* ``ORACLE_18C_SERVICE_NAME``: Service name for Oracle 18c (default: "XEPDB1")
* ``ORACLE_23AI_SERVICE_NAME``: Service name for Oracle 23c (default: "FREEPDB1")
* ``ORACLE_USER``: Username for Oracle (default: "app")
* ``ORACLE_PASSWORD``: Password for Oracle (default: "super-secret")
* ``ORACLE_SYSTEM_PASSWORD``: System password for Oracle (default: "super-secret")

API
---

.. automodule:: pytest_databases.docker.oracle
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
