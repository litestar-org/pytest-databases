Contribution guide
==================

Setting up the environment
--------------------------

1. `Install MariaDB <https://mariadb.com/kb/en/binary-packages/>`_
2. ``make install``

Code contributions
------------------

Workflow
++++++++

1. `Fork <https://github.com/litestar-org/pytest-databases/fork>`_ the `Pytest Database Alchemy repository <https://github.com/litestar-org/pytest-databases>`_
2. Clone your fork locally with git
3. `Set up the environment <#setting-up-the-environment>`_
4. Make your changes
5. (Optional) Run ``pre-commit run --all-files`` to run linters and formatters. This step is optional and will be executed
   automatically by git before you make a commit, but you may want to run it manually in order to apply fixes
6. Commit your changes to git
7. Push the changes to your fork
8. Open a `pull request <https://docs.github.com/en/pull-requests>`_. Give the pull request a descriptive title
   indicating what it changes. If it has a corresponding open issue, the issue number should be included in the title as
   well. For example a pull request that fixes issue ``bug: Increased stack size making it impossible to find needle #100``
   could be titled ``fix(#100): Make needles easier to find by applying fire to haystack``

.. tip:: Pull requests and commits all need to follow the
    `Conventional Commit format <https://www.conventionalcommits.org>`_

.. note:: To run the integration tests locally, you will need the `ODBC Driver for SQL Server <https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server?view=sql-server-ver16>`_, one option is using `unixODBC <https://www.unixodbc.org/>`_.

Selective continuous integration
++++++++++++++++++++++++++++++++

Pull requests use the changed files to choose the smallest safe test scope:

- A provider implementation or provider test change runs that provider on Python 3.12. Clientless import compatibility
  checks still run on every supported Python version.
- Shared runtime, dependency, lock, or workflow changes run every provider once on Python 3.12.
- Documentation-only changes build the documentation and do not start containers or pull container images.
- An unrecognized path fails closed by running every provider on Python 3.12.

The ``Select provider tests`` job summary records the changed paths, selection reason, tests, images, and estimated job
and image-pull counts. This is the first place to look when a provider job did or did not run.

Add the ``ci:full`` label to a pull request to run every provider on Python 3.9 through 3.14. The same full matrix runs
nightly and can be started manually from GitHub Actions. Adding or removing ``ci:full`` starts a new selection run.

``CI required`` is the stable required-check name. It verifies the selector and every job the selector requested while
allowing jobs that were intentionally out of scope to remain skipped.

Maintainers changing branch protection should use this order:

1. Merge the workflow and wait for ``CI required`` to succeed on ``main``.
2. Add ``CI required`` to the required status checks.
3. Confirm a pull request cannot merge when an expected provider or compatibility job fails.
4. Remove obsolete individual or matrix-generated check names only after the stable check is required.

Guidelines for writing code
----------------------------

- All code should be fully `typed <https://peps.python.org/pep-0484/>`_. This is enforced via
  `mypy <https://mypy.readthedocs.io/en/stable/>`_.
- Shipped package behavior should be tested. CI helper scripts and workflow presentation do not add repository tests.
  Package tests are enforced via `pytest <https://docs.pytest.org/en/stable/>`_.
- All code should be properly formatted. This is enforced via `black <https://black.readthedocs.io/en/stable/>`_ and `Ruff <https://beta.ruff.rs/docs/>`_.

Writing and running tests
+++++++++++++++++++++++++

Coming soon.

Project documentation
---------------------

The documentation is located in the ``/docs`` directory and is `ReST <https://docutils.sourceforge.io/rst.html>`_ and
`Sphinx <https://www.sphinx-doc.org/en/master/>`_. If you're unfamiliar with any of those,
`ReStructuredText primer <https://www.sphinx-doc.org/en/master/lib/usage/restructuredtext/basics.html>`_ and
`Sphinx quickstart <https://www.sphinx-doc.org/en/master/lib/usage/quickstart.html>`_ are recommended reads.

Running the docs locally
++++++++++++++++++++++++

You can serve the documentation with ``make serve-docs``, or build them with ``make docs``.

Creating a new release
----------------------

1. Increment the version in `pyproject.toml <https://github.com/litestar-org/pytest-databases/blob/main/pyproject.toml>`_.
    .. note:: The version should follow `semantic versioning <https://semver.org/>`_ and `PEP 440 <https://www.python.org/dev/peps/pep-0440/>`_.
2. `Draft a new release <https://github.com/litestar-org/pytest-databases/releases/new>`_ on GitHub

   * Use ``vMAJOR.MINOR.PATCH`` (e.g. ``v1.2.3``) as both the tag and release title
   * Fill in the release description. You can use the "Generate release notes" function to get a draft for this
3. Commit your changes and push to ``main``
4. Publish the release
5. Go to `Actions <https://github.com/litestar-org/pytest-databases/actions>`_ and approve the release workflow
6. Check that the workflow runs successfully
