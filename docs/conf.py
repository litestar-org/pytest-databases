"""Sphinx documentation configuration for pytest-databases."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from pytest_databases.__metadata__ import __project__, __version__

sys.path.insert(0, str(Path("..").resolve()))

current_year = datetime.now(tz=timezone.utc).year

project = __project__
project_copyright = f"{current_year}, Litestar Organization"
author = "Litestar Organization"
release = __version__

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_design",
    "auto_pytabs.sphinx_ext",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "shibuya"
html_title = "Pytest Databases"
pygments_style = "dracula"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_logo = "_static/logo.svg"
html_favicon = "_static/logo.svg"

html_theme_options = {
    "accent_color": "amber",
    "github_url": "https://github.com/litestar-org/pytest-databases",
    "discord_url": "https://discord.gg/litestar",
}

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autodoc_type_aliases = {
    "Container": "docker.models.containers.Container",
}

autodoc_mock_imports = [
    "OpenSSL",
    "adbc_driver_flightsql",
    "azure",
    "google",
    "oracledb",
    "psycopg",
    "pymongo",
    "redis",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pytest": ("https://docs.pytest.org/en/latest", None),
}
