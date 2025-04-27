Enabling Database Plugins
=========================

After installing the necessary extras, you need to tell pytest to load the corresponding plugin(s). Add the plugin path(s) to your pytest configuration.

Choose **one** of the following methods:

**1. `conftest.py`**:

.. code-block:: python

   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins = [
       "pytest_databases.docker.postgres",
       "pytest_databases.docker.redis",
   ]

**2. `pyproject.toml`**:

.. code-block:: toml

   [tool.pytest.ini_options]
   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins = [
       "pytest_databases.docker.postgres",
       "pytest_databases.docker.redis",
   ]

**3. `pytest.ini`**:

.. code-block:: ini

   [pytest]
   # Example: Enable PostgreSQL and Redis plugins
   pytest_plugins =
       pytest_databases.docker.postgres
       pytest_databases.docker.redis
