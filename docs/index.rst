:layout: landing
:description: Reusable test fixtures for any and all databases.

.. container::
    :name: home-head

    .. container::

        .. raw:: html

            <div class="title-with-logo">
               <div class="brand-text">Pytest Databases</div>
            </div>

        .. container:: badges
           :name: badges

            .. image:: https://img.shields.io/pypi/v/pytest-databases?labelColor=202235&color=edb641&logo=python&logoColor=edb641
               :alt: PyPI Version

            .. image:: https://img.shields.io/pypi/pyversions/pytest-databases?labelColor=202235&color=edb641&logo=python&logoColor=edb641
               :alt: Supported Python Versions

.. rst-class:: lead

   The pytest-databases library is designed to simplify database testing by providing pre-configured setups for a wide range of database types and versions.

.. container:: buttons wrap

   .. raw:: html

      <a href="getting-started/index.html" class="btn-no-wrap">Get Started</a>
      <a href="supported-databases/index.html" class="btn-no-wrap">Usage & API Docs</a>

.. grid:: 1 1 2 2
    :padding: 0
    :gutter: 2

    .. grid-item-card:: :octicon:`versions` Changelog
      :link: changelog
      :link-type: doc

      The latest updates and enhancements to Pytest Databases.

    .. grid-item-card:: :octicon:`issue-opened` Issues
      :link: https://github.com/litestar-org/pytest-databases/issues

      Report issues or suggest new features.

    .. grid-item-card:: :octicon:`comment-discussion` Discussions
      :link: https://github.com/litestar-org/pytest-databases/discussions

      Join discussions, pose questions, or share insights.

    .. grid-item-card:: :octicon:`beaker` Contributing
      :link: contribution-guide
      :link-type: doc

      Contribute to this project's growth with code, docs, and more.

.. toctree::
   :caption: Contents:
   :hidden:

   getting-started/index
   supported-databases/index

.. toctree::
    :titlesonly:
    :caption: Contributing
    :hidden:

    changelog
    contribution-guide
    Available Issues <https://github.com/litestar-org/pytest-databases/issues>
    Code of Conduct <https://github.com/litestar-org/.github?tab=coc-ov-file#readme>
