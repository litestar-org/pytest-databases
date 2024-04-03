# MIT License

# Copyright (c) 2024 Litestar

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# Configuration file for the Sphinx documentation builder.
from __future__ import annotations

import os

from pytest_databases.__metadata__ import __version__ as version

# -- Environmental Data ------------------------------------------------------

# -- Project information -----------------------------------------------------
project = "pytest-databases"
author = "Litestar Org"
release = version
release = os.getenv("_PYTEST-DATABASES_DOCS_BUILD_VERSION", version.rsplit(".")[0])
copyright = "2024, Litestar Org"  # noqa: A001

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.githubpages",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "docs.fix_missing_references",
    "sphinx_copybutton",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinx_click",
    "sphinx_toolbox.collapse",
    "sphinx_design",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "msgspec": ("https://jcristharif.com/msgspec/", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20/", None),
    "litestar": ("https://docs.litestar.dev/latest/", None),
    "click": ("https://click.palletsprojects.com/en/8.1.x/", None),
    "redis": ("https://redis-py.readthedocs.io/en/stable/", None),
    "jinja2": ("https://jinja.palletsprojects.com/en/latest/", None),
}
PY_CLASS = "py:class"
PY_RE = r"py:.*"
PY_METH = "py:meth"
PY_ATTR = "py:attr"
PY_OBJ = "py:obj"

nitpicky = True
nitpick_ignore = [
    # type vars and aliases / intentionally undocumented
    (PY_CLASS, "T"),
]
nitpick_ignore_regex = [
    (PY_RE, r"pytest_databases.*\.T"),
]

napoleon_google_docstring = True
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
napoleon_attr_annotations = True

autoclass_content = "class"
autodoc_class_signature = "separated"
autodoc_default_options = {"special-members": "__init__", "show-inheritance": True, "members": True}
autodoc_member_order = "bysource"
autodoc_typehints_format = "short"
autodoc_type_aliases = {"FilterTypes": "FilterTypes"}

autosectionlabel_prefix_document = True

todo_include_todos = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Style configuration -----------------------------------------------------
html_theme = "litestar_sphinx_theme"
html_static_path = ["_static"]
html_js_files = ["versioning.js"]
html_css_files = ["style.css"]
html_show_sourcelink = True
html_title = "Pytst Databases"


html_theme_options = {
    "logo": {
        "link": "https://litestar.dev",
    },
    "use_page_nav": False,
    "github_repo_name": "pytest-databases",
    "announcement": "This documentation is currently under development.",
    "pygment_light_style": "xcode",
    "pygment_dark_style": "lightbulb",
    "navigation_with_keys": True,
    "extra_navbar_items": {
        "Documentation": "index",
        "Community": {
            "Contributing": {
                "description": "Learn how to contribute to the Litestar project",
                "link": "https://docs.litestar.dev/latest/contribution-guide.html",
                "icon": "contributing",
            },
            "Code of Conduct": {
                "description": "Review the etiquette for interacting with the Litestar community",
                "link": "https://github.com/litestar-org/.github?tab=coc-ov-file",
                "icon": "coc",
            },
            "Security": {
                "description": "Overview of Litestar's security protocols",
                "link": "https://github.com/litestar-org/.github?tab=coc-ov-file#security-ov-file",
                "icon": "coc",
            },
        },
        "About": {
            "Litestar Organization": {
                "description": "Details about the Litestar organization",
                "link": "https://litestar.dev/about/organization",
                "icon": "org",
            },
            "Releases": {
                "description": "Explore the release process, versioning, and deprecation policy for Litestar",
                "link": "https://litestar.dev/about/litestar-releases",
                "icon": "releases",
            },
        },
        "Release notes": {
            "What's new in 2.0": "release-notes/whats-new-2",
            "2.x Changelog": "https://docs.litestar.dev/2/release-notes/changelog.html",
            "1.x Changelog": "https://docs.litestar.dev/1/release-notes/changelog.html",
        },
        "Help": {
            "Discord Help Forum": {
                "description": "Dedicated Discord help forum",
                "link": "https://discord.gg/litestar-919193495116337154",
                "icon": "coc",
            },
            "GitHub Discussions": {
                "description": "GitHub Discussions ",
                "link": "https://github.com/orgs/litestar-org/discussions",
                "icon": "coc",
            },
            "Stack Overflow": {
                "description": "We monitor the <code><b>litestar</b></code> tag on Stack Overflow",
                "link": "https://stackoverflow.com/questions/tagged/litestar",
                "icon": "coc",
            },
        },
    },
}
