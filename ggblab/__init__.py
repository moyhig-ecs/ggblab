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


def connect_to_bridge(host: str = "127.0.0.1", port: int = 8765):
    """Configure the module to forward calls to a bridge started by
    `ggblab_core.AppletInjector.start_proxy_mode`.

    After calling this, module-level `function`/`command` will be
    available and will forward to the bridge at `host:port`.
    """
    try:
        import ggblab_core2 as _g2
    except Exception as e:
        raise RuntimeError("ggblab_core2 is required for connect_to_bridge") from e

    try:
        _g2.connect_to_bridge(host=host, port=port)
    except Exception:
        raise

    # Also expose simple module-level forwarding helpers that call
    # ggblab_core.applet.AppletInjector.*_sync via the bridge.
    try:

        async def _mod_function(name, args=None, timeout=None):
            payload = {"type": "function", "payload": {"name": name, "args": args}}
            import importlib

            client = None
            for modname in (
                "comm_bridge.client",
                "ggblab.comm_bridge.client",
                "ggblab_core.comm_bridge.client",
            ):
                try:
                    client = importlib.import_module(modname)
                    break
                except Exception:
                    continue
            if client is None:
                raise RuntimeError("comm_bridge.client not available")
            resp = await asyncio.to_thread(
                client.request, payload, host, port, timeout or 10.0
            )
            if isinstance(resp, dict):
                if "reply" in resp:
                    resp = resp["reply"]
                if isinstance(resp, dict) and "payload" in resp:
                    p = resp["payload"]
                    if isinstance(p, dict) and "value" in p:
                        return p["value"]
                if "value" in resp:
                    return resp["value"]
            return resp

        async def _mod_command(command, timeout=None):
            payload = {"type": "command", "payload": command}
            import importlib

            client = None
            for modname in (
                "comm_bridge.client",
                "ggblab.comm_bridge.client",
                "ggblab_core.comm_bridge.client",
            ):
                try:
                    client = importlib.import_module(modname)
                    break
                except Exception:
                    continue
            if client is None:
                raise RuntimeError("comm_bridge.client not available")
            resp = await asyncio.to_thread(
                client.request, payload, host, port, timeout or 10.0
            )
            if isinstance(resp, dict):
                return resp.get("reply", resp) or resp
            return resp

        globals()["function"] = _mod_function
        globals()["command"] = _mod_command

        # Patch the default instance if already created
        if _default_geo is not None:
            try:
                setattr(_default_geo, "function", _mod_function)
                setattr(_default_geo, "command", _mod_command)
            except Exception:
                pass
    except Exception:
        # best-effort only
        pass

    return True


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
# allow those workflows, the replacement can be disabled by setting the
# environment variable `GGBLAB_DISABLE_MODULE_REPLACEMENT` to any value.
# ---------------------------------------------------------------------------
if os.environ.get("GGBLAB_DISABLE_MODULE_REPLACEMENT"):
    # Module replacement explicitly disabled via environment variable.
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
