"""ggblab: Interactive geometric scene construction with Python and GeoGebra.

This package provides a JupyterLab extension that opens a GeoGebra applet
and enables bidirectional communication between Python and GeoGebra through
a dual-channel architecture (IPython Comm + Unix socket/TCP WebSocket).

Main Components:
    - GeoGebra: Primary interface for controlling GeoGebra applets
    - ggb_comm: Communication layer (IPython Comm + out-of-band socket)
    - ggb_construction: GeoGebra file (.ggb) loader and saver
    - ggb_parser: Dependency graph parser for GeoGebra constructions

Example:
    >>> from ggblab import GeoGebra
    >>> ggb = await GeoGebra().init()
    >>> await ggb.command("A=(0,0)")
    >>> value = await ggb.function("getValue", ["A"])
"""

try:
    from ._version import __version__
except ImportError:
    # Fallback when using the package in dev mode without installing
    # in editable mode with pip. It is highly recommended to install
    # the package from a stable release or in editable mode: https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs
    import warnings
    warnings.warn("Importing 'ggblab' outside a proper installation.")
    __version__ = "dev"

from .parser import ggb_parser
from .construction import ggb_construction
from .comm import ggb_comm
from .ggbapplet import GeoGebra, GeoGebraSyntaxError, GeoGebraSemanticsError

def _jupyter_labextension_paths():
    """Return the JupyterLab extension paths.
    
    Returns:
        list: Extension metadata for JupyterLab.
    """
    return [{
        "src": "labextension",
        "dest": "ggblab"
    }]
