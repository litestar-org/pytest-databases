Enabling Database Plugins
=========================

Each provider is a pytest plugin module under ``pytest_databases.docker``. Load the ones you need from your
``conftest.py``. This example enables PostgreSQL and Redis:

.. code-block:: python

   pytest_plugins = [
       "pytest_databases.docker.postgres",
       "pytest_databases.docker.redis",
   ]
