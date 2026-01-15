import asyncio
import re
import ipykernel.connect

from IPython.core.getipython import get_ipython
from ipylab import JupyterFrontEnd

from .comm import ggb_comm
from .construction import ggb_construction
from .parser import ggb_parser, tokenize_with_commas, flatten


class GeoGebraSyntaxError(Exception):
    """Exception raised for syntax errors in GeoGebra commands.
    
    Raised when a command string cannot be properly tokenized or
    contains invalid syntax that prevents parsing.
    
    Attributes:
        command (str): The command that caused the error
        message (str): Explanation of the error
    """
    def __init__(self, command, message):
        self.command = command
        self.message = message
        super().__init__(f"Syntax error in command '{command}': {message}")


class GeoGebraSemanticsError(Exception):
    """Exception raised for semantic errors in GeoGebra commands.
    
    Raised when a command references objects that don't exist in the applet,
    or violates other semantic constraints.
    
    Current capabilities:
        - Object existence checking: Verifies referenced objects are present
          in the applet via getAllObjectNames()
    
    Future capabilities (when metadata becomes available):
        - Type checking: Validate argument types match command signatures
        - Scope/visibility checking: Ensure objects are in appropriate scope
        - Overload resolution: Handle commands with multiple signatures
    
    Limitations:
        Complete command validation is not performed because GeoGebra does not
        maintain a public, versioned, machine-readable command schema. The official
        GitHub repository is outdated and does not reflect the live API.
        
        Strategy: Validation is passive—we check what we can (object existence),
        then rely on GeoGebra to accept or reject the command. This is more robust
        than maintaining a potentially incorrect static schema.
    
    Attributes:
        command (str): The command that caused the error
        message (str): Explanation of the error
        missing_objects (list, optional): List of referenced but non-existent objects
    """
    def __init__(self, command, message, missing_objects=None):
        self.command = command
        self.message = message
        self.missing_objects = missing_objects or []
        super().__init__(f"Semantics error in command '{command}': {message}")


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
        construction (ggb_construction): File loader/saver for .ggb files
        parser (ggb_parser): Dependency graph parser with command learning
        comm (ggb_comm): Communication layer (initialized after init())
        kernel_id (str): Current Jupyter kernel ID
        app (JupyterFrontEnd): ipylab frontend interface
        check_syntax (bool): Enable syntax validation (default: False)
        check_semantics (bool): Enable semantic validation (default: False)
        _applet_objects (set): Cached object names from applet (updated by command/function)
    
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
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.initialized = False
        self.construction = ggb_construction()
        self.parser = ggb_parser()
        self.check_syntax = False
        self.check_semantics = False
        self._applet_objects = set()  # Cache of known objects
  
    async def init(self):
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
        if not self.initialized:
            self.comm = ggb_comm()
            self.comm.start()
            while self.comm.socketPath is None:
                await asyncio.sleep(.01)
            self.comm.register_target()

            _connection_file = ipykernel.connect.get_connection_file()
            self.kernel_id = re.search(r'kernel-(.*)\.json', _connection_file).group(1)
            
            self.app = JupyterFrontEnd()
            self.app.commands.execute('ggblab:create', {
                'kernelId': self.kernel_id,
                'commTarget': 'ggblab-comm',
                'insertMode': 'split-right',
                'socketPath': self.comm.socketPath,
              # 'wsPort': self.comm.wsPort,
            })
            
            # Initialize object cache
            await self.refresh_object_cache()
            
            self._initialized = True
        return self
    
    async def refresh_object_cache(self):
        """Refresh the cached set of known objects from the applet.
        
        Called automatically during init() and can be called manually to
        synchronize the object cache with current applet state.
        """
        try:
            objects = await self.function("getAllObjectNames")
            if objects:
                self._applet_objects = set(objects)
        except Exception as e:
            print(f"Warning: Could not refresh object cache: {e}")
    
    async def function(self, f, args=None):
        """Call a GeoGebra API function.
        
        Args:
            f (str): GeoGebra API function name (e.g., "getValue", "getXML").
            args (list, optional): Function arguments. Defaults to None.
        
        Returns:
            Any: Function return value from GeoGebra.
            
        Example:
            >>> value = await ggb.function("getValue", ["A"])
            >>> xml = await ggb.function("getXML", ["A"])
            >>> all_objs = await ggb.function("getAllObjectNames")
        """
        r = await self.comm.send_recv({
            "type": "function",
            "payload": {
                "name": f,
                "args": args
            }
        })
        return r['value']

    async def command(self, c):
        """Execute a GeoGebra command with optional validation.
        
        Args:
            c (str): GeoGebra command string (e.g., "A=(0,0)", "Circle(A, 2)").
        
        Returns:
            dict: Response from GeoGebra (typically includes object label).
            
        Raises:
            GeoGebraSyntaxError: If syntax check is enabled and command has syntax errors.
            GeoGebraSemanticsError: If semantics check is enabled and validation fails.
            
        Example:
            >>> await ggb.command("A=(0,0)")
            >>> await ggb.command("B=(3,4)")
            >>> await ggb.command("Circle(A, Distance(A, B))")
            
            >>> # With validation
            >>> ggb.check_syntax = True
            >>> ggb.check_semantics = True
            >>> await ggb.command("Circle(A, B)")  # Validates syntax and references
        """
        # Syntax check: validate command can be tokenized
        if self.check_syntax:
            try:
                tokenize_with_commas(c)
            except Exception as e:
                raise GeoGebraSyntaxError(c, str(e))
        
        # Semantics check: validate referenced objects exist in applet
        if self.check_semantics:
            try:
                tokens = list(flatten(tokenize_with_commas(c)))
                # Filter tokens that look like object names (start with letter)
                object_tokens = [t for t in tokens if t and isinstance(t, str) 
                                and t[0].isalpha() and t not in ('true', 'false')]
                
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
        
        # Update object cache on successful command
        if result and 'label' in result:
            self._applet_objects.add(result['label'])
        
        return result