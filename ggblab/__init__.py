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


# ---------------------------------------------------------------------------
# Replace the module object in `sys.modules` with the default GeoGebra
# instance so `import ggblab as ggb` yields an object that behaves like
# a `GeoGebra` instance. This is intentional for PyCall/pyimport usage
# where callers expect the imported object to provide the instance API.
# We do NOT call `init()` here; only construct the controller object.
# ---------------------------------------------------------------------------
try:
    import sys as _sys
    inst = _default_geo or _create_default_instance()
    if inst is not None:
        try:
            # Copy a few helpful module-level symbols onto the instance so
            # existing import patterns like `ggb.GeoGebra` still work when
            # the module object is replaced.
            try:
                setattr(inst, 'GeoGebra', GeoGebra)
                setattr(inst, 'ggb_comm', ggb_comm)
                setattr(inst, 'ggb_file', ggb_file)
            except Exception:
                pass
        except Exception:
            pass
        try:
            _sys.modules[__name__] = inst
        except Exception:
            # If replacing sys.modules fails for any reason, do nothing.
            pass
except Exception:
    # Never let import fail because of this compatibility step
    pass
    >>> from ggblab import GeoGebra
    >>> ggb = await GeoGebra().init()
    >>> await ggb.command("A=(0,0)")
    >>> value = await ggb.function("getValue", ["A"])
    
    Note:
        Heavy I/O and parsing implementations have been moved to the optional
        package `ggblab_extra`. If you need DataFrame-based construction I/O
        or the full parser implementation, install and import `ggblab_extra`.
        This package keeps lightweight shims for backward compatibility which
        will be deprecated and removed in a future major release.

The public API has been split between a compact core (this package) and an
optional collection of helpers in ``ggblab_extra``. Callers that rely on
the extras should install that package; otherwise consumers should prefer
the minimal APIs provided here. Deprecated shims exist to ease migration and
will emit DeprecationWarning when used.
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

from .comm import ggb_comm, ggb_comm_instance
from .file import ggb_file
from .ggbapplet import GeoGebra, GeoGebraSemanticsError, GeoGebraSyntaxError

# Construction I/O was moved from `ggblab_extra` into the core package.
# Expose `DataFrameIO` / `ConstructionIO` at package level so installs
# that import these symbols (or the build) will include the module.
try:
    from .construction_io import ConstructionIO, DataFrameIO  # noqa: F401
except Exception:
    # Optional dependencies used by `construction_io` may be missing during
    # some build steps; don't make the entire package import fail.
    pass

# Backward compatibility alias
ggb_construction = ggb_file

# Deprecated imports - maintained for backward compatibility
# These will be removed in ggblab 1.0.0
# Use 'from ggblab_extra import ggb_parser' instead
try:
    import warnings

    from ggblab_extra.construction_parser import ggb_parser
    
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
    import warnings

    from ggblab_extra.persistent_counter import PersistentCounter as _PersistentCounter

    class PersistentCounter(_PersistentCounter):
        """Deprecated shim; use ggblab_extra.PersistentCounter instead."""

        def __init__(self, *args, **kwargs):
            """Warn about deprecated import and initialize the underlying counter."""
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


def load_ipython_extension(ipython):
    """Register the ggblab comm target when the kernel extension loads.

    This function registers the comm handler provided by `ggb_comm_instance`.
    It is idempotent and safe to call multiple times.
    """
    try:
        km = getattr(ipython, "kernel", None)
        if km is None:
            return
        cm = getattr(km, "comm_manager", None)
        if cm is None:
            return
        if not globals().get("_jupyter_ggblab_registered"):
            try:
                # Use the module-level singleton to perform registration
                ggb_comm_instance.register_target()
                globals()["_jupyter_ggblab_registered"] = True
                import logging as _logging
                _logging.getLogger(__name__).debug("ggblab: comm target registered (jupyter.ggblab)")
            except Exception as e:
                import logging as _logging
                _logging.getLogger(__name__).exception("ggblab: comm registration failed")
        # Attempt to register IPython magics (non-critical)
        try:
            from .ipymagic import register_ggb_magic
            try:
                register_ggb_magic(ipython)
            except Exception:
                # Don't let magic registration break extension load
                pass
        except Exception:
            pass
    except Exception:
        # Defensive: never raise from load_ipython_extension
        pass


# Auto-register IPython extension when `import ggblab` happens inside
# an IPython environment (e.g., Jupyter notebook). This is best-effort
# and must not fail import if IPython is unavailable.
try:
    from IPython import get_ipython as _get_ipython
    _ip = _get_ipython()
    if _ip is not None:
        try:
            load_ipython_extension(_ip)
        except Exception:
            # Non-critical: avoid breaking normal imports
            pass
except Exception:
    pass


# ---------------------------------------------------------------------------
# Module-level forwarding to a default GeoGebra instance (deprecated)
# Allows callers using PyCall/pyimport to do `ggb = pyimport("ggblab")`
# and then call `ggb.init()` etc. This is a compatibility shim and will
# emit a `DeprecationWarning` when used. Prefer `from ggblab import GeoGebra`.
# ---------------------------------------------------------------------------
import warnings as _warnings

_default_geo = None
_module_api_warned = False

def _create_default_instance():
    global _default_geo, _module_api_warned
    if _default_geo is None:
        if not _module_api_warned:
            _warnings.warn(
                "Using the module-level ggblab API is deprecated. "
                "Import `GeoGebra` and instantiate it explicitly: `from ggblab import GeoGebra; ggb = GeoGebra()`.",
                DeprecationWarning,
                stacklevel=3,
            )
            _module_api_warned = True
        try:
            _default_geo = GeoGebra()
        except Exception:
            # If construction fails, leave _default_geo as None and
            # let attribute access raise an informative error later.
            _default_geo = None
    return _default_geo

def __getattr__(name):
    """Forward unknown module attributes to a default GeoGebra instance.

    This enables `ggb = pyimport('ggblab'); ggb.init()` to work while
    keeping the explicit `GeoGebra` class available for direct use.
    """
    inst = _create_default_instance()
    if inst is None:
        raise AttributeError(f"ggblab module attribute '{name}' not found and default GeoGebra instance could not be created")
    return getattr(inst, name)

def __dir__():
    names = list(globals().keys())
    inst = _default_geo
    if inst is not None:
        try:
            names.extend([n for n in dir(inst) if n not in names])
        except Exception:
            pass
    return sorted(names)
