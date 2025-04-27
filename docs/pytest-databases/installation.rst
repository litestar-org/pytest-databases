Installation
============

Install the base package using pip:

.. code-block:: bash

   pip install pytest-databases

To include support for specific databases, install the package with extras. For example, to add PostgreSQL support:

.. code-block:: bash

   pip install pytest-databases[postgres]

You can specify multiple databases:

.. code-block:: bash

   pip install pytest-databases[postgres,mysql,redis]

See the :doc:`../getting-started/installation` guide for a full list of available extras and detailed installation instructions.
