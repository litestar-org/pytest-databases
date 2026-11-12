================
Teradata Vantage
================

Clientless container and external endpoint fixtures for Teradata Vantage.

Teradata Vantage Express is typically distributed as a VM/OVA image rather than a public Docker Hub repository.
``pytest_databases.docker.teradata`` supports both an opt-in BYO container image (``teradata_service``) and an external
Teradata Vantage VM or cloud endpoint (``teradata_external_service``). Both fixtures skip cleanly when their
configuration environment variable is unset.

Examples
========

.. tab-set::

    .. tab-item:: External endpoint

        .. code-block:: python

            from __future__ import annotations


            def test_teradata_external(teradata_external_service) -> None:
                import teradatasql

                with teradatasql.connect(**teradata_external_service.connection_config) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        assert cur.fetchone() == (1,)

    .. tab-item:: BYO container image

        .. code-block:: python

            from __future__ import annotations


            def test_teradata_container(teradata_service) -> None:
                import teradatasql

                with teradatasql.connect(**teradata_service.connection_config) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        assert cur.fetchone() == (1,)

Configuration
=============

- ``TERADATA_IMAGE`` / ``TERADATA_TEST_IMAGE``: BYO container image reference for ``teradata_service`` (unset by default; skips when unset).
- ``TERADATA_EXTERNAL_HOST`` / ``TERADATA_HOST``: Hostname or IP address for ``teradata_external_service`` (unset by default; skips when unset).
- ``TERADATA_EXTERNAL_PORT`` / ``TERADATA_PORT``: Gateway port override (defaults to ``1025`` for external endpoints and ephemeral host mapping for containers).
- ``TERADATA_USER`` / ``TERADATA_PASSWORD``: Login credentials (default ``"dbc"``).
- ``TERADATA_DATABASE``, ``TERADATA_LOGMECH``, ``TERADATA_LOGDATA``, ``TERADATA_SSLMODE``, ``TERADATA_ENCRYPTDATA``, ``TERADATA_TMODE``: Optional session parameters included in ``connection_config`` when set.
- ``TERADATA_STARTUP_TIMEOUT``: Readiness wait timeout in seconds (default ``300.0``).

Reference
=========

.. automodule:: pytest_databases.docker.teradata
    :members:
