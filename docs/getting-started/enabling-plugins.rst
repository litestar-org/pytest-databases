Enabling Database Plugins
=========================

After installing the necessary extras, you need to tell pytest to load the corresponding plugin(s). Add the plugin path(s) to your pytest configuration.


.. code-block:: python

   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins = [
       "pytest_databases.docker.postgres",
       "pytest_databases.docker.redis",
   ]
