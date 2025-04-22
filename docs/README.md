# Pytest Database Documentation

This directory contains the documentation for the Pytest Database project. The documentation is built using Sphinx with the Shibuya theme.

## Building the Documentation

1. Install the documentation dependencies:

```bash
`make install`
```

2. Build the documentation:

```bash
make docs
```

The built documentation will be available in the `build/html` directory.

## Documentation Structure

- `docs/` - Contains the source files for the documentation
    - `api/` - API reference documentation
    - `guides/` - User guides and tutorials
    - `_static/` - Static files (images, CSS, etc.)
    - `_templates/` - Custom templates
    - `conf.py` - Sphinx configuration
    - `index.rst` - Main documentation page

## Contributing to the Documentation

1. Make your changes to the relevant RST files in the `source` directory
2. Build the documentation to verify your changes
3. Submit a pull request with your changes

## Style Guide

- Use reStructuredText for all documentation files
- Follow the Google Python Style Guide for docstrings
- Include code examples where appropriate
- Keep the documentation up to date with code changes
