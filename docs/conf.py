import sys
from datetime import datetime
from pathlib import Path

from pytest_databases.__metadata__ import __project__, __version__

sys.path.insert(0, str(Path("..").resolve()))


# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
current_year = datetime.now().year  # noqa: DTZ005

project = __project__
copyright = f"{current_year}, Litestar Organization"  # noqa: A001
author = "Litestar Organization"
release = __version__

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.githubpages",
    "sphinx_copybutton",
    "sphinx_click",
    "sphinx_design",
    "auto_pytabs.sphinx_ext",
    "myst_parser",
    "sphinx_autodoc_typehints",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "shibuya"
html_title = "Pytest Databases"
pygments_style = "dracula"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_logo = "_static/logo.svg"
html_favicon = "_static/logo.svg"  # Optional: use logo as favicon

# Shibuya theme options: https://shibuya.lepture.com/install/
html_theme_options = {
    "accent_color": "amber",
    "github_url": "https://github.com/litestar-org/pytest-databases",
    "discord_url": "https://discord.gg/litestar",
}

# Autodoc settings
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

# Mock imports for modules not needed during doc generation
autodoc_mock_imports = ["OpenSSL"]

# Intersphinx settings
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pytest": ("https://docs.pytest.org/en/latest", None),
}
