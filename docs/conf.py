"""Sphinx configuration of the ggblab documentation (version 2)."""
import importlib.metadata

project = "ggblab"
author = "Manabu Higashida"
copyright = "2025, Manabu Higashida"
release = importlib.metadata.version("ggblab")
version = release

extensions = [
    "myst_parser",
    "sphinx_rtd_theme",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
]
source_suffix = [".md"]
root_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "sphinx_rtd_theme"
myst_heading_anchors = 3
# The pages take whole sections of README.md; a section's first heading is one level below the page title by design.
suppress_warnings = ["myst.header"]
autodoc_member_order = "bysource"
autodoc_typehints = "description"


def _verbatim(app, what, name, obj, options, lines):
    """The docstrings are plain text, not reStructuredText: show them as they are written."""
    if lines:
        lines[:] = ["::", ""] + ["    " + line for line in lines] + [""]


def setup(app):
    app.connect("autodoc-process-docstring", _verbatim)
