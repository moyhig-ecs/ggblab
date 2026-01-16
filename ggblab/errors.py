"""Custom exception hierarchy for ggblab.

Exceptions are organized into two main branches:
- Command validation errors: Caught before execution (syntax, semantics)
- Applet errors: From GeoGebra responses during execution

Exception Hierarchy:

    GeoGebraError
    ├── GeoGebraCommandError
    │   ├── GeoGebraSyntaxError
    │   │   Raised: Command string cannot be tokenized or has syntax errors
    │   │
    │   └── GeoGebraSemanticsError
    │       Raised: Referenced objects don't exist in applet
    │
    └── GeoGebraAppletError
        Raised: GeoGebra applet produces an error event (runtime errors)

Usage Examples:

    # Catch all GeoGebra errors
    try:
        await ggb.command("Circle(A, B)")
    except GeoGebraError as e:
        print(f"GeoGebra error: {e}")

    # Catch only command validation errors
    except GeoGebraCommandError as e:
        print(f"Command validation failed: {e}")

    # Catch specific validation errors
    except GeoGebraSyntaxError as e:
        print(f"Syntax error: {e.command}")
    except GeoGebraSemanticsError as e:
        print(f"Missing objects: {e.missing_objects}")

    # Catch applet runtime errors
    except GeoGebraAppletError as e:
        print(f"Applet error: {e.error_message}")
"""


class GeoGebraError(Exception):
    """Base exception for all GeoGebra-related errors.
    
    This is the root exception for all ggblab exceptions, allowing users to catch
    any GeoGebra-related error with a single except clause.
    """
    pass


class GeoGebraCommandError(GeoGebraError):
    """Base exception for command validation errors.
    
    Raised when a command fails pre-flight validation (syntax or semantics).
    This intermediate class groups command-related errors together, allowing users
    to catch validation failures separately from applet errors.
    """
    pass


class GeoGebraSyntaxError(GeoGebraCommandError):
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


class GeoGebraSemanticsError(GeoGebraCommandError):
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


class GeoGebraAppletError(GeoGebraError):
    """Exception raised for errors from the GeoGebra applet.
    
    Raised when the GeoGebra applet produces an error event in response to
    a command or API call. These errors originate from GeoGebra itself rather
    than pre-flight validation.
    
    Attributes:
        error_message (str): Error message from GeoGebra applet
        command (str, optional): The command that triggered the applet error
        error_type (str, optional): Error classification (e.g., 'AppletError')
    
    Example:
        >>> raise GeoGebraAppletError(
        ...     error_message="Unbalanced brackets",
        ...     error_type="AppletError"
        ... )
    """
    def __init__(self, error_message, command=None, error_type=None):
        self.error_message = error_message
        self.command = command
        self.error_type = error_type
        msg = f"GeoGebra applet error: {error_message}"
        if command:
            msg += f" (in command '{command}')"
        if error_type:
            msg += f" [{error_type}]"
        super().__init__(msg)
