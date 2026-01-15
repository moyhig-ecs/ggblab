# GeoGebra Command Validation Strategy

## Overview

ggblab provides optional syntax and semantic validation for GeoGebra commands. However, due to fundamental constraints in GeoGebra's public API, validation is intentionally **passive and incomplete**.

## Current Validation Capabilities

### Syntax Validation (`check_syntax`)

Validates that a command string can be successfully tokenized and parsed.

```python
ggb.check_syntax = True
await ggb.command("Circle(A, B)")  # ✓ Valid syntax
await ggb.command("Circle(A, B)))")  # ✗ GeoGebraSyntaxError
```

**Implementation**: Uses `parser.tokenize_with_commas()` to parse the command string.

### Semantic Validation (`check_semantics`)

Currently checks only **object existence**: verifies that all referenced object names exist in the applet.

```python
await ggb.command("A=(0,0)")
await ggb.command("B=(1,1)")

ggb.check_semantics = True
await ggb.command("Circle(A, B)")  # ✓ Both A and B exist
await ggb.command("Circle(A, C)")  # ✗ GeoGebraSemanticsError: C not found
```

**Implementation**: 
1. Tokenizes the command
2. Extracts tokens that look like object identifiers (start with letter)
3. Calls `getAllObjectNames()` to get applet objects
4. Checks if all referenced objects exist

## Constraints and Limitations

### 1. No Canonical Command Schema

GeoGebra does not publicly maintain a machine-readable schema of available commands, their signatures, or argument types.

### 2. Official Source is Outdated

The [official GeoGebra GitHub repository](https://github.com/geogebra/geogebra) is significantly outdated:
- Missing newer APIs like `evalCommandGetLabels()`
- Command signatures may differ from the live version
- No versioning tied to specific GeoGebra releases

### 3. Dynamic API Evolution

GeoGebra continuously adds and modifies commands without stable versioning. A static schema would quickly become incorrect and misleading.

## Validation Philosophy: Passive and Trust-Based

Rather than maintaining an incomplete schema, ggblab uses a **passive validation strategy**:

1. **Validate what's verifiable**: Check that referenced objects exist
2. **Trust the source**: Let GeoGebra accept or reject the command
3. **Fail gracefully**: Invalid commands will error on execution with GeoGebra's feedback

This approach is more robust than fighting against an evolving API.

## Future Enhancements

### Option A: Static Schema (if available)

Once GeoGebra publishes command metadata (or if internal inspection APIs become available), validation can extend to:

- **Type checking**: Verify argument types match command signatures
- **Arity validation**: Check the number of arguments is correct
- **Scope checking**: Ensure objects are in appropriate visibility scope
- **Overload resolution**: Handle commands with multiple valid signatures

### Option B: Passive Error Learning (proposed, not yet implemented)

An alternative approach that leverages GeoGebra's error feedback directly:

**Mechanism**: 
- GeoGebra's applet displays popup error dialogs for invalid commands
- These error messages are forwarded to the kernel as events with `type: Error`
- Errors accumulate in `ggb.comm.recv_events.queue` for inspection
- The `command()` method could monitor this queue after execution

**Proposed Implementation**:
1. Execute the command asynchronously
2. Poll `recv_events.queue` for Error events within a timeout window
3. Parse the error message from GeoGebra (e.g., "Object B not found", "Type mismatch", etc.)
4. Extract structured information about what failed
5. Optionally re-raise as a more informative `GeoGebraSemanticsError`

**Advantages**:
- Uses GeoGebra's actual behavior rather than a static schema
- Automatically stays in sync with GeoGebra's current implementation
- Captures error messages in user's language if supported
- No maintenance of command metadata needed

**Challenges**:
- Requires parsing variable error message formats
- Error dialogs may not always be shown (depends on GeoGebra settings)
- Adds latency (must wait for error dialog to appear)
- May not capture all error types

**Future Work**: Implement passive validation as a retry/feedback mechanism that learns from GeoGebra's actual error responses.

## Implementation Notes

### Object Filtering

The semantic validator filters tokens to identify likely object names:
- Must start with a letter (excludes operators, numbers)
- Excludes reserved keywords like `true`, `false`
- Only tokens that match this heuristic are checked

This avoids false positives on operators and literals.

### Performance

Object existence checks require a call to `getAllObjectNames()` on each `command()` call when `check_semantics=True`. For performance-critical applications, consider batching commands or disabling validation.

### Error Event Queue Structure

The kernel's event receiver maintains an error queue in `ggb.comm.recv_events.queue`. Error events are labeled with `type: Error` and contain:
- Error message from GeoGebra's applet popup
- Timestamp
- Context about which command or operation triggered the error

Future passive validation implementations can inspect this queue to provide enhanced error feedback without requiring a static command schema.

### Error Information

`GeoGebraSemanticsError` includes:
- `error.command`: The command that failed
- `error.message`: Explanation of the error
- `error.missing_objects`: List of referenced but non-existent objects (if applicable)

## Recommended Usage

**Development/debugging**: Enable both validations to catch obvious mistakes early

```python
ggb.check_syntax = True
ggb.check_semantics = True
```

**Production**: Disable validation for performance if you're confident in command correctness

```python
ggb.check_syntax = False
ggb.check_semantics = False
```

**Hybrid**: Enable syntax validation (cheap) but not semantics (requires async API call)

```python
ggb.check_syntax = True
ggb.check_semantics = False
```

## See Also

- [Architecture](architecture.md) - Overall system design
- [ggbapplet.py](../ggblab/ggbapplet.py) - Implementation details
