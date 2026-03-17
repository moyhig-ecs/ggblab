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

import asyncio
import os

from .comm import ggb_comm_instance
from .file import ggb_file
from .ggbapplet import GeoGebra
# Lightweight parser and schema helpers — import lazily when possible
try:
    from .parser import ggb_parser as ggb_parse
except Exception:
    ggb_parse = None

try:
    from .schema import ggb_schema as ggb_schema
except Exception:
    ggb_schema = None

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
            stacklevel=3,
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
    ggb_parser = type(
        "ggb_parser",
        (),
        {
            "__call__": lambda self, *args, **kwargs: (
                _deprecated_import("ggb_parser"),
                _parser_module(*args, **kwargs),
            )[1]
        },
    )()

except ImportError:
    # ggblab_extra not installed - no backward compatibility
    pass

# Deprecated import shim for PersistentCounter
try:
    import warnings

    from ggblab_extra.persistent_counter import \
        PersistentCounter as _PersistentCounter

    class PersistentCounter(_PersistentCounter):
        """Deprecated shim; use ggblab_extra.PersistentCounter instead."""

        def __init__(self, *args, **kwargs):
            """Warn about deprecated import and initialize the underlying counter."""
            warnings.warn(
                "Importing 'PersistentCounter' from 'ggblab' is deprecated. "
                "Use 'from ggblab_extra import PersistentCounter' instead. "
                "This compatibility layer will be removed in ggblab 1.0.0.",
                DeprecationWarning,
                stacklevel=2,
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
    return [{"src": "labextension", "dest": "ggblab"}]


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

                _logging.getLogger(__name__).debug(
                    "ggblab: comm target registered (jupyter.ggblab)"
                )
            except Exception:
                import logging as _logging

                _logging.getLogger(__name__).exception(
                    "ggblab: comm registration failed"
                )
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
# an IPython environment (e.g., Jupyter notebook). This used to be
# automatic but is now opt-in to avoid surprising side-effects during
# plain `import`. To enable the old behaviour set the environment
# variable `GGBLAB_ENABLE_AUTOLOAD=1` before importing.
try:
    from IPython import get_ipython as _get_ipython

    _ip = _get_ipython()
    if _ip is not None and os.environ.get("GGBLAB_ENABLE_AUTOLOAD"):
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


def _create_default_instance(suppress_warning: bool = False):
    global _default_geo, _module_api_warned
    if _default_geo is None:
        if not _module_api_warned and not suppress_warning:
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


def connect_to_bridge(host: str = "127.0.0.1", port: int = 8765, *, export_globals: bool = False):
    """Deprecated compatibility wrapper.

    Prefer calling `ggblab.comm_bridge.connect(...)` directly. This helper
    remains for backward compatibility and will forward to the canonical
    implementation while emitting a DeprecationWarning.
    """
    import warnings

    try:
        from . import comm_bridge as _cb

        warnings.warn(
            "ggblab.connect_to_bridge() is deprecated; use ggblab.comm_bridge.connect() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return _cb.connect(host=host, port=port, export_globals=export_globals)
    except Exception as e:
        raise RuntimeError("failed to locate comm_bridge.connect") from e


class _AppletHelper:
    """Helper to explicitly inject/open a GeoGebra frontend panel.

    Usage:
        ggb = await ggblab.applet.inject(appName="suite")
    """

    async def inject(self, appName: str = "suite", insertMode: str = "split-right"):
        try:
            from ggblab_core2.applet import AppletInjector2

            inj = AppletInjector2()
            # AppletInjector2.open may return an initialized GeoGebra instance
            ggb = inj.open(appName=appName, insertMode=insertMode)
            return ggb
        except Exception:
            # Fallback: try to import local GeoGebra controller and init
            try:
                from .ggbapplet import GeoGebra

                ggb = GeoGebra()
                # call init in an async-aware way
                try:
                    if hasattr(ggb, "_run_sync"):
                        ggb._run_sync(ggb.init(appName=appName))
                    else:
                        import asyncio as _asyncio

                        await _asyncio.ensure_future(ggb.init(appName=appName))
                except Exception:
                    pass
                return ggb
            except Exception:
                raise


# Public helper instance for explicit applet injection
applet = _AppletHelper()


def __getattr__(name):
    """Forward unknown module attributes to a default GeoGebra instance.

    This enables `ggb = pyimport('ggblab'); ggb.init()` to work while
    keeping the explicit `GeoGebra` class available for direct use.
    """
    inst = _create_default_instance()
    if inst is None:
        raise AttributeError(
            f"ggblab module attribute '{name}' not found and default GeoGebra instance could not be created"
        )
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


# ---------------------------------------------------------------------------
# Replace the module object in `sys.modules` with the default GeoGebra
# instance so `import ggblab as ggb` yields an object that behaves like
# a `GeoGebra` instance. This is intentional for PyCall/pyimport usage
# where callers expect the imported object to provide the instance API.
# We do NOT call `init()` here; only construct the controller object.
#
# The module-replacement is optional and may interfere with some build
# steps (for example `jupyter labextension develop --overwrite .`). To
# avoid surprising import-time side-effects the replacement is disabled by
# default. To opt in to the old behaviour set the environment variable
# `GGBLAB_ENABLE_MODULE_REPLACEMENT` to any value.
# ---------------------------------------------------------------------------
if not os.environ.get("GGBLAB_ENABLE_MODULE_REPLACEMENT"):
    # Module replacement disabled by default to avoid import-time side effects.
    pass
else:
    try:
        import sys as _sys

        inst = _default_geo or _create_default_instance(suppress_warning=True)
        if inst is not None:
            try:
                # Copy a few helpful module-level symbols onto the instance so
                # existing import patterns like `ggb.GeoGebra` still work when
                # the module object is replaced.
                try:
                    setattr(inst, "GeoGebra", GeoGebra)
                    # Convenience forwarders
                    try:
                        if "connect_to_bridge" in globals():
                            setattr(
                                inst, "connect_to_bridge", globals()["connect_to_bridge"]
                            )
                        if "function" in globals():
                            setattr(inst, "function", globals()["function"])
                        if "command" in globals():
                            setattr(inst, "command", globals()["command"])
                        # Expose the `schema` submodule on the instance so that
                        # `pyimport("ggblab").schema.ggb_schema` works for PyCall.
                        try:
                            import importlib

                            schema_mod = importlib.import_module(__name__ + ".schema")
                            # Prefer exposing the compiled XMLSchema object
                            # produced by `ggb_schema` as `ggb.schema` so that
                            # `pyimport("ggblab").schema.ggb_schema` and
                            # `pyimport("ggblab").schema` behave usefully in
                            # PyCall consumers. If instantiation fails or the
                            # compiled schema is unavailable, fall back to the
                            # module object.
                            try:
                                schema_inst_cls = getattr(schema_mod, "ggb_schema", None)
                                if schema_inst_cls is not None:
                                    try:
                                        schema_inst = schema_inst_cls()
                                        schema_obj = getattr(schema_inst, "schema", None)
                                        if schema_obj is not None:
                                            setattr(inst, "schema", schema_obj)
                                        else:
                                            setattr(inst, "schema", schema_mod)
                                    except Exception:
                                        # If constructing the loader fails, expose module
                                        setattr(inst, "schema", schema_mod)
                                else:
                                    setattr(inst, "schema", schema_mod)
                            except Exception:
                                setattr(inst, "schema", schema_mod)
                        except Exception:
                            pass

                        # Also expose ggb_file, ggb_parse, ggb_schema names on the instance
                        try:
                            if "ggb_file" in globals():
                                setattr(inst, "ggb_file", globals()["ggb_file"])
                            if "ggb_parse" in globals():
                                setattr(inst, "ggb_parse", globals()["ggb_parse"])
                            if "ggb_schema" in globals():
                                setattr(inst, "ggb_schema", globals()["ggb_schema"])
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # setattr(inst, 'ggb_comm', ggb_comm)
                    # setattr(inst, 'ggb_file', ggb_file)
                except Exception:
                    pass
                # Copy core module metadata so tools like autoreload that expect
                # module objects (with __name__, __spec__, etc.) continue to work.
                try:
                    mod = _sys.modules.get(__name__)
                    if mod is not None:
                        for attr in (
                            "__name__",
                            "__package__",
                            "__spec__",
                            "__file__",
                            "__path__",
                            "__loader__",
                        ):
                            if hasattr(mod, attr):
                                try:
                                    setattr(inst, attr, getattr(mod, attr))
                                except Exception:
                                    pass
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
