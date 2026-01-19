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

from .comm import ggb_comm
from .file import ggb_file
from .ggbapplet import GeoGebra, GeoGebraSyntaxError, GeoGebraSemanticsError

# Backward compatibility alias
ggb_construction = ggb_file

# Deprecated imports - maintained for backward compatibility
# These will be removed in ggblab 1.0.0
# Use 'from ggblab_extra import ggb_parser' instead
try:
    from ggblab_extra.parser import ggb_parser
    import warnings
    
    def _deprecated_import(name):
        warnings.warn(
            f"Importing '{name}' from 'ggblab' is deprecated. "
            f"Use 'from ggblab_extra import {name}' instead. "
            f"This compatibility layer will be removed in ggblab 1.0.0.",
            DeprecationWarning,
            stacklevel=3
        )
    
    class _DeprecatedModule:
        def __init__(self, name, module):
            self._name = name
            self._module = module
        
        def __getattr__(self, attr):
            _deprecated_import(self._name)
            return getattr(self._module, attr)
    
    # Wrap deprecated imports
    _parser_module = ggb_parser
    ggb_parser = type('ggb_parser', (), {
        '__call__': lambda self, *args, **kwargs: (
            _deprecated_import('ggb_parser'),
            _parser_module(*args, **kwargs)
        )[1]
    })()
    
except ImportError:
    # ggblab_extra not installed - no backward compatibility
    pass

# Deprecated import shim for PersistentCounter
try:
    from ggblab_extra.persistent_counter import PersistentCounter as _PersistentCounter
    import warnings

    class PersistentCounter(_PersistentCounter):
        """Deprecated shim; use ggblab_extra.PersistentCounter instead."""

        def __init__(self, *args, **kwargs):
            warnings.warn(
                "Importing 'PersistentCounter' from 'ggblab' is deprecated. "
                "Use 'from ggblab_extra import PersistentCounter' instead. "
                "This compatibility layer will be removed in ggblab 1.0.0.",
                DeprecationWarning,
                stacklevel=2
            )
            super().__init__(*args, **kwargs)

except ImportError:
    # ggblab_extra not installed - no backward compatibility
    pass

def _jupyter_labextension_paths():
    """Return the JupyterLab extension paths.
    
    Returns:
        list: Extension metadata for JupyterLab.
    """
    return [{
        "src": "labextension",
        "dest": "ggblab"
    }]
