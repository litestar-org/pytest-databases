\
.. _db_mysql:

MySQL
=====

Integration with MySQL.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mysql]

Docker Image
------------

`Official MySQL Docker Image <https://hub.docker.com/_/mysql>`_

Configuration
-------------

* ``MYSQL_IMAGE``: Docker image to use for MySQL (default: "mysql:latest")
* ``XDIST_MYSQL_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``MYSQL_USER``: Username for MySQL (default: "root")
* ``MYSQL_PASSWORD``: Password for MySQL (default: "super-secret")
* ``MYSQL_DATABASE``: Database name for MySQL (default: "pytest_databases")

API
---

.. automodule:: pytest_databases.docker.mysql
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
