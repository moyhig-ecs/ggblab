"""High-level GeoGebra applet controller used by notebooks and the JupyterLab plugin.

`GeoGebra` is the public-facing class that manages communication channels
(IPython Comm + out-of-band socket) and provides async methods for sending
commands and calling GeoGebra API functions. Heavy I/O helpers and
analysis tools live in the optional `ggblab_extra` package.
"""

import asyncio
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import threading

import ipykernel.connect
import os
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urlunsplit
from IPython.display import display, JSON
import subprocess
# Note: import `ipylab` lazily inside `init()` to avoid hard dependency
# and accidental panel injection when running in non-JupyterLab hosts.
from IPython.core.getipython import get_ipython

from ggblab.utils import flatten

from .comm import ggb_comm
from .errors import (
    GeoGebraAppletError,
    GeoGebraCommandError,
    GeoGebraError,
    GeoGebraSemanticsError,
    GeoGebraSyntaxError,
)
from .file import ggb_file
from .parser import ggb_parser


# Exception hierarchy is defined in errors.py and imported above
class GeoGebra:
    """Main interface for controlling GeoGebra applets from Python.
    
    This class implements a singleton pattern to ensure only one GeoGebra
    instance per kernel session. It provides async methods for sending
    commands and calling GeoGebra API functions.
    
    The communication uses a dual-channel architecture:
    - IPython Comm: Primary control channel
    - Unix socket/TCP WebSocket: Out-of-band response delivery during cell execution
    
    Semantic Validation:
    - check_syntax: Validates command strings can be tokenized
    - check_semantics: Validates referenced objects exist in applet
    - Future: Type checking, scope/visibility validation
    
    Attributes:
        file (ggb_file): GeoGebra file (.ggb) loader and saver
        construction: Backward compatibility alias for file attribute
        parser: Dependency graph parser with command learning
        comm (ggb_comm): Communication layer (initialized after init())
        kernel_id (str): Current Jupyter kernel ID
        app (JupyterFrontEnd): ipylab frontend interface
        check_syntax (bool): Enable syntax validation (default: False)
        check_semantics (bool): Enable semantic validation (default: False)
        _applet_objects (set): Cached object names from applet (updated by command/function)
    
    Note:
        The parser attribute lives in this package and provides tokenization
        and command-cache features used for syntax/semantics checks.

        Note:
            Heavy I/O and convenience helpers (DataFrame construction,
            persistence helpers such as ``ConstructionIO.save_dataframe``,
            and richer parser implementations) have been moved to the
            optional ``ggblab_extra`` package. Install ``ggblab_extra`` to
            access those features; the core package keeps lightweight shims
            and will emit DeprecationWarning when using deprecated helpers.
    
    Example:
        >>> ggb = GeoGebra()
        >>> await ggb.init()
        >>> await ggb.command("A=(0,0)")
        >>> result = await ggb.function("getValue", ["A"])
        
        >>> # With validation
        >>> ggb.check_syntax = True
        >>> ggb.check_semantics = True
        >>> await ggb.command("Circle(A, B)")
    """

    _instance = None

    def __new__(cls):
        """Create or return the singleton GeoGebra instance for this kernel."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize default attributes for the GeoGebra controller."""
        self.initialized = False
        self.file = ggb_file()  # .ggb file I/O
        self.construction = self.file  # Backward compatibility alias
        self.parser = ggb_parser()
        self.check_syntax = False
        self.check_semantics = False
        self._applet_objects = set()  # Cache of known objects

    async def copy_connection_to_clipboard(self) -> None:
        """Build a minimal connection JSON and copy it to the system clipboard.

        Intended usage from a notebook (macOS):
            ggb = GeoGebra()
            await ggb.init(use_vscode=True)
            await ggb.copy_connection_to_clipboard()

        This writes a JSON object like:
            {"kernelId": "...", "socketPath": "...", "connection_file": "...", "baseUrl": "...", "token": "..."}

        Uses `pbcopy` on macOS; falls back to printing the JSON if clipboard is unavailable.
        """
        try:
            payload = {'kernelId': getattr(self, 'kernel_id', None) or '', 'socketPath': getattr(self.comm, 'socketPath', None) or ''}
            # connection file
            try:
                cf = ipykernel.connect.get_connection_file()
                if cf:
                    payload['connection_file'] = cf
            except Exception:
                pass

            # try to discover running server info (best-effort)
            try:
                from jupyter_server.serverapp import list_running_servers
                servers = list(list_running_servers())
                if servers:
                    srv = servers[0]
                    base_url = srv.get('base_url') or srv.get('baseUrl') or None
                    raw_url = srv.get('url') or srv.get('server_url') or None
                    token = srv.get('token') or srv.get('password') or None
                    if raw_url:
                        parts = urlsplit(raw_url)
                        qs = parse_qs(parts.query)
                        for k in ('token', 'access_token'):
                            if k in qs and qs[k]:
                                token = token or qs[k][0]
                        base_no_q = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', '', ''))
                        if (not base_url) or (str(base_url).strip() == '/'):
                            base_url = base_no_q
                    if base_url:
                        payload['baseUrl'] = base_url
                    payload['token'] = token or ''
            except Exception:
                # ignore if jupyter_server not present
                pass

            txt = json.dumps(payload)
            # Prefer pyperclip if available (cross-platform). Fallback to pbcopy on macOS.
            wrote = False
            try:
                import pyperclip
                try:
                    pyperclip.copy(txt)
                    display(JSON(payload))
                    wrote = True
                except Exception:
                    wrote = False
            except Exception:
                wrote = False

            if not wrote:
                try:
                    p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
                    p.communicate(txt.encode('utf8'))
                    display(JSON(payload))
                    wrote = True
                except Exception:
                    wrote = False

            if not wrote:
                # Fallback: print the JSON so user can copy manually
                try:
                    display(JSON(payload))
                    print('ggblab: clipboard write failed; connection JSON printed above')
                except Exception:
                    print(txt)
        except Exception as e:
            try:
                print('ggblab: failed to copy connection to clipboard:', e)
            except Exception:
                pass
  
    async def init(self, appName: str = 'suite', use_vscode: Optional[bool] = None):
        """Initialize the GeoGebra widget and communication channels.
        
        This method:
        1. Starts the out-of-band socket server (Unix socket on POSIX, TCP WebSocket on Windows)
        2. Registers the IPython Comm target ('ggblab-comm')
        3. Opens the GeoGebra widget panel via ipylab with communication settings
        4. Initializes the object cache
        
        The widget is launched programmatically to pass kernel-specific settings
        (Comm target, socket path) before initialization, avoiding the limitations
        of fixed arguments from Launcher/Command Palette.
        
        Returns:
            GeoGebra: Self reference for method chaining.
            
        Example:
            >>> ggb = await GeoGebra().init()
            >>> # GeoGebra panel opens in split-right position
        """
        # appName validation is centralized in ggblab_core2.applet

        # Decide whether to open a frontend panel (ipylab) or publish
        # connection info for VS Code. Only run comm startup when the
        # caller explicitly requests `use_vscode=True` to avoid surprising
        # side-effects during import or light-weight usage.
        if not self.initialized:
            try:
                if use_vscode:
                    from ggblab_core2.applet import setup_comm_and_kernel, publish_connection_for_vscode
                    info = await setup_comm_and_kernel(self)
                    self.kernel_id = info.get('kernel_id')
                    try:
                        await publish_connection_for_vscode(self)
                    except Exception:
                        pass
                else:
                    # No comm startup performed here. Users who want a
                    # full comm+frontend experience should use the
                    # AppletInjector2 helpers in `ggblab_core2`.
                    pass
            except Exception:
                # Best-effort: don't fail init if publishing/setup fails
                pass

            # Initialize object cache
            self._applet_objects = set()
            self.initialized = True
        return self
    
    def _is_literal(self, token):
        """Check if token is a literal value (number, string, boolean, math function).
        
        Literals should not be validated as object references. This includes:
        - Numeric literals: 2, 3.14, -5, 1e-3
        - String literals: "text", 'string'
        - Boolean constants: true, false
        - Math functions: sin, cos, sqrt, etc.
        
        Args:
            token: Token to check
            
        Returns:
            bool: True if token is a literal, False if it could be an object reference
        """
        if not isinstance(token, str) or not token:
            return True
        
        # Numeric literals (integers, decimals, scientific notation)
        try:
            float(token)
            return True
        except ValueError:
            pass
        
        # String literals (quoted)
        if token[0] in ('"', "'"):
            return True
        
        # Boolean constants
        if token in ('true', 'false'):
            return True
        
        # Common GeoGebra/math functions
        math_functions = {
            'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2',
            'sinh', 'cosh', 'tanh',
            'sqrt', 'abs', 'log', 'ln', 'log10', 'exp',
            'floor', 'ceil', 'round', 'sgn',
            'random', 'min', 'max', 'sum', 'mean',
        }
        if token in math_functions:
            return True
        
        return False
    
    async def refresh_object_cache(self):
        """Refresh the cached set of known objects from the applet.
        
        Called automatically during init() and can be called manually to
        synchronize the object cache with current applet state.
        """
        try:
            objects = await self.function("getAllObjectNames")
            self._applet_objects = set(objects) if objects else set()
        except Exception as e:
            print(f"Warning: Could not refresh object cache: {type(e).__name__} {e}")
    
    async def function(self, f, args=None):
        """Call a GeoGebra API function via the communication layer.

        Sends a 'function' request to the frontend and returns the inner
        value from the response payload.
        """
        r = await self.comm.send_recv({
            "type": "function",
            "payload": {"name": f, "args": args},
        })
        # Normalize common response shapes
        if isinstance(r, dict):
            if 'value' in r:
                return r['value']
            if 'payload' in r and isinstance(r['payload'], dict) and 'value' in r['payload']:
                return r['payload']['value']
            if 'reply' in r:
                return r['reply']
        return r

    @asynccontextmanager
    async def preserve(self):
        """Snapshot the current construction and restore it on exit.

        Yields:
            A `Snap` object with the following attributes and helpers:
            - `xml` (str | None): GeoGebra construction XML (None on error)
            - `timestamp` (datetime): UTC time when snapshot was taken
            - `size_bytes` (int): byte length of the XML
            - `sha1` (str): SHA1 digest of the XML
            Methods:
            - `await snap.restore()`: immediately restore the saved XML
            - `snap.release()`: drop `xml` to free memory

        Usage examples:
            # automatic restore on exit (no local XML reference kept)
            async with ggb.preserve():
                await ggb.command("A=(1,2)")

            # inspect or restore inside the block
            async with ggb.preserve() as snap:
                print(snap.sha1, snap.size_bytes)
                await snap.restore()

        Notes:
            - The returned `xml` is an immutable Python string; no extra deep-copy
              is performed when yielding it. If you hold `snap.xml` for long
              periods it will retain memory until released or out of scope.
            - If acquiring the XML fails, `xml` will be `None` and no automatic
              restoration will be attempted on exit.
        """
        @dataclass
        class Snap:
            base64_zip: Optional[str]
            # Optionally decoded XML (if the snapshot helper extracts it); may be None
            xml: Optional[str]
            timestamp: datetime
            size_bytes: int
            sha1: str
            _ggb: "GeoGebra"

            async def restore(self) -> None:
                # Prefer restoring via setBase64 when possible
                if self.base64_zip is not None:
                    await self._ggb.function("setBase64", [self.base64_zip])
                    return
                if self.xml is None:
                    return
                # Fallback: attempt to restore XML directly if available
                await self._ggb.function("setXML", [self.xml])

            def release(self) -> None:
                self.xml = None

        try:
            # Acquire a zip+base64 snapshot from the applet to avoid large XML strings
            b64 = await self.function("getBase64")
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to read GeoGebra base64 snapshot (getBase64). Proceeding without backup.")
            b64 = None

        if b64 is not None:
            # Compute SHA1 and size on the decoded bytes
            try:
                decoded = __import__('base64').b64decode(b64)
                sha1 = hashlib.sha1(decoded).hexdigest()
                size = len(decoded)
            except Exception:
                sha1 = hashlib.sha1(b64.encode('utf8')).hexdigest()
                size = len(b64.encode('utf8'))
            snap = Snap(base64_zip=b64, xml=None, timestamp=datetime.utcnow(), size_bytes=size, sha1=sha1, _ggb=self)
        else:
            snap = Snap(base64_zip=None, xml=None, timestamp=datetime.utcnow(), size_bytes=0, sha1="", _ggb=self)

        try:
            yield snap
        finally:
            # Restore using base64 snapshot if available, otherwise attempt XML
            if snap.base64_zip is not None:
                try:
                    await self.function("setBase64", [snap.base64_zip])
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to restore GeoGebra snapshot via setBase64.")
            elif snap.xml is not None:
                try:
                    await self.function("setXML", [snap.xml])
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to restore GeoGebra XML (setXML).")

    async def command(self, c):
        """Execute a GeoGebra command with optional validation.
        
        Args:
            c (str): GeoGebra command string (e.g., "A=(0,0)", "Circle(A, 2)").
        
        Returns:
            dict: Response from GeoGebra (typically includes object label).
            
        Raises:
            GeoGebraSyntaxError: If syntax check is enabled and command has syntax errors.
            GeoGebraSemanticsError: If semantics check is enabled and validation fails.
            GeoGebraAppletError: If GeoGebra applet produces error events during execution.
            
        Example:
            >>> await ggb.command("A=(0,0)")
            >>> await ggb.command("B=(3,4)")
            >>> await ggb.command("Circle(A, Distance(A, B))")
            
            >>> # With validation
            >>> ggb.check_syntax = True
            >>> ggb.check_semantics = True
            >>> await ggb.command("Circle(A, B)")  # Validates syntax and references
            
            >>> # Error handling
            >>> try:
            ...     await ggb.command("Unbalanced(")
            ... except GeoGebraAppletError as e:
            ...     print(f"Applet error: {e.error_message}")
        """
        # Syntax check: validate command can be tokenized
        if self.check_syntax:
            try:
                self.parser.tokenize_with_commas(c)
            except Exception as e:
                raise GeoGebraSyntaxError(c, str(e))
        
        # Semantics check: validate referenced objects exist in applet
        if self.check_semantics:
            try:
                # Refresh object cache before checking
                await self.refresh_object_cache()
                
                # Extract object tokens: tokens in the flattened structure that are
                # not commands (not in command_cache), not commas, and not literals
                t = self.parser.tokenize_with_commas(c)
                object_tokens = [o for o in flatten(t) 
                                if o not in self.parser.command_cache 
                                and o != ","
                                and not self._is_literal(o)]
                
                # Check if referenced objects exist
                missing_objects = [obj for obj in object_tokens 
                                    if obj not in self._applet_objects]
                
                if missing_objects:
                    raise GeoGebraSemanticsError(
                        c, 
                        f"Referenced object(s) do not exist in applet: {missing_objects}",
                        missing_objects
                    )
            except GeoGebraSemanticsError:
                raise
            except Exception as e:
                raise GeoGebraSemanticsError(c, f"Validation error: {e}")
        
        result = await self.comm.send_recv({
            "type": "command",
            "payload": c
        })
        
        # FUTURE: Error event queue processing for enhanced scope learning
        # After command execution, GeoGebra appends error events to self.comm.recv_events.queue:
        #   {'type': 'Error', 'payload': 'Unbalanced brackets'}
        #   {'type': 'Error', 'payload': 'Circle(A, 1 '}
        # 
        # This enables:
        # 1. Real-time error capture: Complement pre-flight validation with actual GeoGebra errors
        # 2. Dynamic scope updates: Track which objects were created despite errors
        # 3. Cross-domain learning: Correlate error patterns with domain-specific semantics
        # 4. Validation refinement: Use GeoGebra's error feedback to improve check_semantics logic
        # 
        # Implementation strategy:
        #   - Drain error queue: while self.comm.recv_events.queue: event = popleft()
        #   - Classify errors: syntax vs semantic vs type errors
        #   - Update validation rules based on error patterns
        #   - Store error context for cross-session learning via parser.command_cache
        
        # Update object cache on successful command
        if result and 'label' in result:
            self._applet_objects.add(result['label'])
        
        return result

    def command_sync(self, c):
        """Synchronous wrapper around `command`.

        Runs the async `command` coroutine in a background thread and
        returns the result. See `function_sync` for rationale.
        """
        return self._run_sync(self.command(c))