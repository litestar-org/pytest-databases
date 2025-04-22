\
.. _db_mariadb:

MariaDB
=======

Integration with MariaDB.

Installation
------------

.. code-block:: bash

   pip install pytest-databases[mariadb]

Docker Image
------------

`Official MariaDB Docker Image <https://hub.docker.com/_/mariadb>`_

Configuration
-------------

* ``MARIADB_IMAGE``: Docker image to use for MariaDB (default: "mariadb:latest")
* ``XDIST_MARIADB_ISOLATION_LEVEL``: Isolation level for xdist workers (default: "database")
* ``MARIADB_USER``: Username for MariaDB (default: "root")
* ``MARIADB_PASSWORD``: Password for MariaDB (default: "super-secret")
* ``MARIADB_DATABASE``: Database name for MariaDB (default: "pytest_databases")

API
---

.. automodule:: pytest_databases.docker.mariadb
   :members:
   :undoc-members:
   :show-inheritance:

Usage Example
-------------

.. code-block:: python

   # Example usage will be added here
   pass
