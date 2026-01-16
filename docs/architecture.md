# ggblab Architecture

This document describes the design rationale and implementation details of ggblab's communication architecture.

## Communication Architecture Overview

ggblab implements a **dual-channel communication design** to enable seamless interaction between the GeoGebra applet (frontend) and Python kernel (backend) while working around inherent limitations of Jupyter's IPython Comm.

### The Challenge: IPython Comm Limitation

IPython Comm, the standard Jupyter communication protocol, has a critical limitation: **it cannot receive messages while a notebook cell is executing**. This presents a problem for interactive geometric applications where:

- User code might be running a long computation or animation loop
- The GeoGebra applet needs to send responses or updates back to Python
- Real-time bidirectional communication is essential for interactive workflows

### Solution: Dual-Channel Design

ggblab addresses this limitation with two complementary communication channels:

## Channel 1: IPython Comm (Primary Channel)

**Technology**: IPython Comm over WebSocket  
**Managed by**: Jupyter/JupyterHub infrastructure  
**Purpose**: Main control channel

### Responsibilities

- Command and function call dispatch from Python → GeoGebra
- Event notifications from GeoGebra → Python (object add/remove/rename, dialogs)
- Configuration and initialization messages
- Heartbeat and status monitoring

### Infrastructure Guarantees

The IPython Comm channel benefits from Jupyter/JupyterHub's robust infrastructure:

- **WebSocket management**: Jupyter maintains the WebSocket connection
- **Reverse proxy support**: Works seamlessly in JupyterHub deployments with reverse proxies
- **Connection health**: Jupyter/JupyterHub guarantees connection integrity and automatic reconnection
- **Security**: Authentication and authorization handled by Jupyter

### Known Limitation

**Cannot receive during cell execution**: When a Python cell is running (e.g., a `for` loop or `await` statement), IPython's event loop is blocked and cannot process incoming Comm messages. This prevents real-time responses from the applet during long-running operations.

## Channel 2: Out-of-Band Socket (Secondary Channel)

**Technology**: Unix Domain Socket (POSIX) / TCP WebSocket (Windows)  
**Managed by**: ggblab backend (`ggb_comm`)  
**Purpose**: Response delivery during cell execution

### Responsibilities

- Deliver GeoGebra API responses when the primary Comm channel is blocked
- Enable `await ggb.function(...)` calls to complete even during cell execution
- Support interactive operations in animation loops or long-running code

### Design Rationale

#### Why Unix Domain Socket on POSIX?

- **Performance**: Lower latency than TCP for local inter-process communication
- **Security**: File system permissions control access; no network exposure
- **Simplicity**: No port conflicts or firewall configuration needed

#### Why TCP WebSocket on Windows?

- **Cross-platform compatibility**: Windows lacks first-class Unix Domain Socket support in some environments
- **Consistent API**: Browser WebSocket API works identically for both transport types
- **Portability**: Ensures ggblab works on Windows without degraded functionality

### Connection Model: Transient, Per-Transaction

Unlike the persistent IPython Comm connection, the out-of-band channel:

1. **Opens a fresh connection** for each `send_recv()` call
2. **Transmits the response** from GeoGebra → Python
3. **Closes immediately** after delivery

**Advantages**:
- No persistent connection to maintain
- No reconnection logic needed (connection failure = transaction failure, simple retry)
- Minimal resource overhead (connections are short-lived)
- Natural backpressure: one pending response per transaction

**Why no auto-reconnection?**
- The connection is transient by design—each transaction creates a new connection
- If a transaction fails, the caller (Python code) receives an exception and can retry
- The primary Comm channel (managed by Jupyter) handles persistent connectivity

## Command Validation (Pre-Flight Checks)

Before sending commands to GeoGebra, ggblab performs optional validation to catch errors early and provide Python-side feedback instead of relying on GeoGebra's timeout-based error signaling.

### Syntax Validation

**Purpose**: Verify command strings can be parsed into valid tokens

**Implementation** (`ggblab/ggbapplet.py`):
```python
if self.check_syntax:
    try:
        self.parser.tokenize_with_commas(c)
    except Exception as e:
        raise GeoGebraSyntaxError(c, str(e))
```

**What it checks**:
- Command string can be tokenized by the parser
- Parentheses, brackets, and braces are balanced
- Basic lexical structure is valid

**What it does NOT check**:
- Command name existence (GeoGebra may support commands not in the parser's command cache)
- Argument count or types
- Semantic correctness (use `check_semantics` for that)

**Usage**:
```python
ggb = await GeoGebra().init()
ggb.check_syntax = True  # Enable syntax validation

try:
    await ggb.command("A=(0,0)")  # Valid
except GeoGebraSyntaxError as e:
    print(f"Syntax error: {e}")
```

**Raises**: `GeoGebraSyntaxError` if tokenization fails

### Semantic Validation

**Purpose**: Verify referenced objects exist in the applet before sending the command

**Status**: Partial implementation (see limitations below)

**Implementation** (`ggblab/ggbapplet.py`):
```python
if self.check_semantics:
    try:
        # Refresh object cache from applet
        await self.refresh_object_cache()
        
        # Extract object tokens: tokens that are
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
```

**What it checks**:
- Object references in the command exist in the applet's object cache
- Refreshes the cache before checking to catch recent additions/deletions

**What it does NOT check** (limitations):
- Command name validity (if `check_syntax` passes, command is assumed valid)
- Argument types or counts (would require full GeoGebra API metadata)
- Scope/visibility (static analysis cannot determine runtime scope)
- Overload resolution (multiple command signatures not distinguished)
- N-ary dependencies (3+ objects creating a single dependent object)

**Why incomplete**: GeoGebra does not maintain a public, versioned, machine-readable command schema. The official GitHub repository is outdated and does not reflect the live API. Maintaining a static schema would be error-prone and fragile.

**Usage**:
```python
ggb = await GeoGebra().init()
ggb.check_semantics = True  # Enable semantic validation

# Attempt to use non-existent object
try:
    await ggb.command("Circle(A, 2)")  # A does not exist
except GeoGebraSemanticsError as e:
    print(f"Semantic error: {e}")
    print(f"Missing objects: {e.missing_objects}")
```

**Raises**: `GeoGebraSemanticsError` if referenced objects don't exist

### Cache Management

**Object Cache**:
- Initialized on `GeoGebra().init()` via `refresh_object_cache()`
- Updated after each successful `command()` execution
- Can be manually refreshed: `await ggb.refresh_object_cache()`

**Cache Accuracy**:
- Reflects the current applet state at check time
- May become stale if objects are added/removed via:
  - Frontend UI (direct user actions in GeoGebra)
  - Multiple Python kernels (if multiple notebooks control the same applet)
- Calling `refresh_object_cache()` explicitly ensures fresh data

**Trade-off**: Prevents false positives (rejecting valid commands) at the cost of occasional false negatives (accepting commands that reference recently-deleted objects, which will timeout).

### Validation Strategy

**Recommended practice**:

```python
# Enable both checks for maximum safety
ggb.check_syntax = True
ggb.check_semantics = True

try:
    await ggb.command("Circle(A, Distance(A, B))")
except GeoGebraSyntaxError:
    print("Command syntax is invalid")
except GeoGebraSemanticsError as e:
    print(f"Objects not found: {e.missing_objects}")
except TimeoutError:
    # Command may have been rejected by GeoGebra despite passing pre-flight checks
    # Check recv_events for error dialogs
    print("Command timed out or was rejected by GeoGebra")
```

**Validation Flow**:

```
Python command(c)
    ↓
check_syntax enabled? → tokenize → SyntaxError
    ↓ (pass)
check_semantics enabled? → refresh cache → extract tokens → check existence → SemanticError
    ↓ (pass)
Send to GeoGebra via out-of-band socket
    ↓
GeoGebra processes (may still fail internally)
    ↓
Timeout after 3 seconds? → Check recv_events for error events
    ↓
Errors found? → GeoGebraAppletError
    ↓
No errors? → Return value or None
```

### Runtime Error Handling: GeoGebraAppletError

**Purpose**: Capture errors that occur during GeoGebra execution, not during pre-flight validation

**How it works**:
1. **Asynchronous error capture**: GeoGebra error events (`{'type': 'Error', 'payload': '...'}`) are queued via the out-of-band socket
2. **Multiple error consolidation**: Consecutive error events are automatically combined into a single exception
3. **Timeout-triggered check**: When `send_recv()` times out waiting for a response, it checks `recv_events` for accumulated error messages
4. **Empty response handling**: If the response arrives but the payload is empty (`None`), a 0.5-second wait allows additional errors to arrive before checking

**Exception hierarchy**:
```
GeoGebraError (base)
├── GeoGebraCommandError (pre-flight validation)
│   ├── GeoGebraSyntaxError
│   └── GeoGebraSemanticsError
└── GeoGebraAppletError (runtime, from applet)
```

**Usage**:
```python
from ggblab.errors import GeoGebraAppletError

try:
    await ggb.command("Unbalanced(")
except GeoGebraAppletError as e:
    print(f"Applet error: {e.error_message}")
    print(f"Error type: {e.error_type}")
```

**Example error flow**:
```
GeoGebra applet receives: "Unbalanced("
    ↓
Applet generates error events:
    {'type': 'Error', 'payload': 'Unbalanced brackets '}
    {'type': 'Error', 'payload': 'Unbalanced( '}
    ↓
send_recv() waits for response (doesn't arrive)
    ↓
Timeout triggers recv_events check
    ↓
Errors found and combined:
    "Unbalanced brackets \nUnbalanced( "
    ↓
GeoGebraAppletError raised with combined message
```

## Data Flow Diagrams

### Normal Command Execution (Primary Channel)

```
Python Kernel                    Frontend (Browser)
     |                                  |
     |  1. command("A=(0,0)")           |
     |  2. Syntax & semantic checks     |
     |  3. Send via IPython Comm        |
     |--------------------------------->|
     |      via IPython Comm            |
     |                                  |
     |                      2. Execute GeoGebra command
     |                                  |
     |  3. Response (label)             |
     |<---------------------------------|
     |      via IPython Comm            |
     |                                  |
```

### Function Call During Cell Execution (Dual Channel)

```
Python Cell (running)            Frontend (Browser)            ggb_comm (backend)
     |                                  |                              |
     |  1. await function("getValue")   |                              |
     |--------------------------------->|                              |
     |      via IPython Comm            |                              |
     |                                  |                              |
     |  (Python blocked, cannot receive)|                              |
     |                                  |                              |
     |                      2. Call GeoGebra API                       |
     |                                  |                              |
     |                      3. Response ready                          |
     |                                  |                              |
     |                                  |  4. Open out-of-band socket  |
     |                                  |----------------------------->|
     |                                  |                              |
     |  5. Response delivered           |                              |
     |<-----------------------------------------------------------------|
     |      via Unix socket / WebSocket |                              |
     |                                  |                              |
     |  (await completes)               |  6. Close connection         |
     |                                  |<-----------------------------|
```

### Error Event Capture (Dual Channel)

```
Python Cell (running)            Frontend (Browser)            ggb_comm (backend)
     |                                  |                              |
     |  1. command("Unbalanced(")       |                              |
     |--------------------------------->|                              |
     |                                  |                              |
     |                      2. Execute → Error!
     |                                  |                              |
     |                                  |  3. Queue error events       |
     |                                  |----------------------------->|
     |                                  |  Error event #1              |
     |                                  |  Error event #2              |
     |  (Python blocked waiting)        |                              |
     |                                  |                              |
     |  4. Timeout after 3 seconds      |                              |
     |                                  |                              |
     |  5. Check recv_events            |                              |
     |<----|  Retrieve error events     |                              |
     |     |  Combine messages          |                              |
     |     |  Raise GeoGebraAppletError |                              |
```

## Implementation Details

### Backend: `ggb_comm` (ggblab/comm.py)

**Responsibilities**:
- Start Unix socket server (POSIX) or TCP WebSocket server (Windows)
- Register IPython Comm target (`ggblab-comm`), kept singular because IPython Comm cannot receive during cell execution and multiplexing via multiple targets would not solve that constraint
- Provide `send_recv(msg)` API that:
  1. Sends `msg` via IPython Comm to frontend
  2. Waits for response on the out-of-band socket
  3. Returns response to caller

**Server Initialization**:
```python
async def server(self):
    if os.name in ['posix']:
        # Unix Domain Socket
        _fd, self.socketPath = tempfile.mkstemp(prefix="/tmp/ggb_")
        os.close(_fd)
        os.remove(self.socketPath)
        async with unix_serve(self.client_handle, path=self.socketPath) as self.server_handle:
            await asyncio.Future()  # Run indefinitely
    else:
        # TCP WebSocket
        async with serve(self.client_handle, "localhost", 0) as self.server_handle:
            self.wsPort = self.server_handle.sockets[0].getsockname()[1]
            await asyncio.Future()
```

**Client Handler**:
```python
async def client_handle(self, client_id):
    self.clients.add(client_id)
    try:
        async for msg in client_id:
            _data = json.loads(msg)
            _id = _data.get('id')
            
            # Route event-type messages to recv_events queue
            # Messages with 'id' are command responses; messages without 'id' are events.
            if _id:
                # Response message: store in recv_logs for send_recv() to retrieve
                self.recv_logs[_id] = _data['payload']
            else:
                # Event message: queue for event processing
                self.recv_events.put(_data)
    finally:
        self.clients.remove(client_id)
```

**Message Routing Strategy**:
- **Responses** (with `id`): Keyed by message ID in `recv_logs` for `send_recv()` to retrieve
- **Events** (without `id`): Queued in `recv_events` for asynchronous event processing

This enables real-time error event capture and dialog message delivery during cell execution.

### Frontend: Widget Connection Logic (src/widget.tsx)

**Comm Setup**:
```typescript
const comm = kernel.createComm(props.commTarget || 'ggblab-comm');
comm.open('HELO from GGB').done;

comm.onMsg = async (msg) => {
    const command = JSON.parse(msg.content.data as any);
    // Execute command or function
    // ...
    // Send response back via out-of-band socket if available
    if (socketPath || wsPort) {
        await sendViaSocket(response);
    }
};
### Widget Launch Strategy and Applet Parameter Limitations

GeoGebra applets expose a limited set of startup parameters, documented at:

- https://geogebra.github.io/docs/reference/en/GeoGebra_App_Parameters/

In practice, only `appletOnLoad` provides a JavaScript hook at load time; other parameters do not allow passing dynamic kernel communication configuration to the widget. Additionally, launching from the JupyterLab Launcher or Command Palette supplies fixed arguments only, which prevents injecting per-session communication details before the widget is created.

To ensure the kernel↔widget communication is configured before initialization, ggblab launches the widget programmatically from a notebook cell using ipylab:

1. The Python helper `GeoGebra().init()` prepares communication settings (Comm target, socket path/port) in the kernel.
2. It then triggers the frontend command `ggblab:create` via ipylab with the prepared settings.
3. The widget initializes with the provided configuration, enabling immediate two-way communication.

This strategy avoids the limitations of Launcher/Command Palette (fixed args) and the applet parameter model, guaranteeing reliable setup for the dual-channel communication described above.
```

**Out-of-Band Socket Connection** (per response):
```typescript
// Pseudo-code (actual implementation uses kernel2.requestExecute)
if (socketPath) {
    ws = unix_connect(socketPath);
} else {
    ws = connect(`ws://localhost:${wsPort}/`);
}
ws.send(JSON.stringify(response));
ws.close();
```

### Message ID Correlation

To match responses with requests when multiple operations are in flight:

1. Backend generates unique `id` for each `send_recv()` call (UUID)
2. Frontend receives command with `id` in the Comm message
3. Frontend includes same `id` in response sent via out-of-band socket
4. Backend matches response by `id` in `recv_logs` dictionary

## Error Handling

### Primary Channel (IPython Comm) Error Handling

**Responsibility**: Jupyter/JupyterHub infrastructure  
**Status**: Robust and automatic

The IPython Comm channel inherits error handling from Jupyter:

- **Connection errors**: Jupyter detects WebSocket failures and handles reconnection
- **Message delivery**: Guaranteed via Jupyter's message queuing and acknowledgment
- **User notification**: Connection status visible in JupyterLab UI (kernel indicator)
- **Recovery**: Automatic reconnection when connection is lost and restored

No explicit error handling required in ggblab for the primary channel.

### Out-of-Band Channel Error Handling

**Responsibility**: ggblab backend and frontend  
**Status**: Timeout-based with event queueing

The out-of-band channel operates independently with dual responsibilities:

#### 1. Response Delivery (Timeout-Based)

The out-of-band socket has a **3-second timeout** for command responses:

```python
# In ggblab/comm.py send_recv()
try:
    async with asyncio.timeout(3.0):
        # Wait for response to arrive via out-of-band socket
        while not (_id in self.recv_logs):
            await asyncio.sleep(0.01)
        value = self.recv_logs.pop(_id, None)
        return value
except TimeoutError:
    print(f"TimeoutError in send_recv {msg}")
    return { 'type': 'error', 'message': 'TimeoutError in send_recv' }
```

If no response arrives within 3 seconds, a timeout error is returned.

#### 2. Event Delivery (Queue-Based)

Real-time events (error dialogs, object notifications) are captured and queued via the out-of-band socket:

```python
# In frontend widget.tsx
const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
            try {
                // Detect GeoGebra error dialogs
                (node as HTMLElement).querySelectorAll('div.dialogMainPanel > div.dialogTitle').forEach((n) => {
                    const msg = JSON.stringify({
                        "type": n.textContent,  // e.g., "Error", "Warning"
                        "payload": n2.textContent
                    });
                    // Send via both channels during cell execution
                    comm.send(msg);  // Primary channel (blocked during execution)
                    await callRemoteSocketSend(kernel2, msg, socketPath, wsUrl);  // Out-of-band channel
                });
            } catch (e) { /* handle */ }
        });
    });
});
```

**Backend event processing**:
```python
# Events arrive via out-of-band socket without 'id' field
if not _id:
    self.recv_events.put(_data)  # Queue for later processing
```

Python code can then drain the event queue after commands complete:
```python
# Future implementation: Process queued events
while not self.comm.recv_events.empty():
    event = self.comm.recv_events.get_nowait()
    if event['type'] == 'Error':
        print(f"GeoGebra error: {event['payload']}")
```

#### GeoGebra API Constraint: No Explicit Error Responses

**Critical limitation**: The GeoGebra API does NOT provide explicit error response codes or callbacks for invalid commands.

This means:
- When a command fails (e.g., invalid syntax, reference to non-existent object), GeoGebra does not send an error response via the out-of-band socket
- No error codes, error messages, or structured error data are returned
- The only signals are:
  1. **Timeout after 3 seconds** (command was rejected silently)
  2. **Error dialog popup** (captured and forwarded via out-of-band socket)

**Example**:
```python
# This will timeout because GeoGebra sends no response for invalid commands
try:
    result = await applet.evalCommand("DeleteObject(NonExistent)")
except TimeoutError:
    print("GeoGebra rejected the command (no explicit error returned)")
    # Check if an error dialog was posted
    if not applet.comm.recv_events.empty():
        event = applet.comm.recv_events.get_nowait()
        if event['type'] == 'Error':
            print(f"Error details: {event['payload']}")
```

#### Error Handling Summary

| Channel | Error Detection | Delivery | Recovery |
|---------|-----------------|----------|----------|
| IPython Comm | Jupyter infrastructure | Command dispatch | Jupyter handles reconnection |
| Out-of-band socket (responses) | 3-sec timeout | Message ID correlation | `TimeoutError` exception to Python |
| Out-of-band socket (events) | Event queue | Type-based routing | Queue processing via `recv_events` |
| GeoGebra API | Dialog popups | DOM mutation observer | Dialog events forwarded to Python |

**Current Limitations**:
- Non-dialog errors result in timeout with minimal context
- Response timeout is fixed at 3 seconds (not configurable)

### Future Error Handling Improvements (v0.8.x)

To improve error handling on the out-of-band channel:

1. **Event Queue Processing**
   - Drain `recv_events` queue after command execution
   - Extract error dialogs and parse for context information
   - Return structured error objects with type and message

2. **Custom Timeout Configuration**
   - Allow `GeoGebra(timeout=5.0)` to set custom timeout per applet instance
   - Allow `command(..., timeout=10.0)` for command-specific timeout

3. **Dialog Message Extraction**
   - Parse GeoGebra dialog DOM for structured error details
   - Map dialog types to error codes (e.g., "Syntax error", "Undefined variable")
   - Return error object with context to Python

4. **Dynamic Scope Learning from Errors**
   - Capture error events in `recv_events` queue
   - Correlate with `check_semantics` validation logic
   - Refine validation rules based on actual GeoGebra responses

## Resource Cleanup and Lifecycle Management

### Graceful Shutdown

ggblab implements proper resource cleanup through the widget's `dispose()` lifecycle hook:

**Frontend Widget Disposal** ([src/widget.tsx](../src/widget.tsx)):
```typescript
dispose(): void {
    console.log("GeoGebraWidget is being disposed.");
    window.dispatchEvent(new Event('close'));
    super.dispose();
}
```

When the GeoGebra panel is closed:

1. **Widget disposal triggered**: JupyterLab calls `dispose()` on the `GeoGebraWidget` instance
2. **Close event dispatched**: `window.dispatchEvent(new Event('close'))` signals cleanup to any active listeners
3. **IPython Comm cleanup**: The Comm connection is automatically closed by Jupyter/JupyterHub infrastructure when the widget is disposed
4. **Kernel resource release**: The secondary kernel connection (used for out-of-band WebSocket setup) is released

**Backend Resource Cleanup** ([ggblab/comm.py](../ggblab/comm.py)):
```python
async def server(self):
    if os.name in ['posix']:
        # Unix Domain Socket with context manager
        async with unix_serve(self.client_handle, path=self.socketPath) as self.server_handle:
            await asyncio.Future()  # Run indefinitely
    else:
        # TCP WebSocket with context manager
        async with serve(self.client_handle, "localhost", 0) as self.server_handle:
            await asyncio.Future()
```

The out-of-band socket server uses `async with` context managers:
- **Automatic cleanup**: Socket resources are released when the context exits
- **Per-transaction connections**: Each message response opens and closes a connection, preventing resource leaks
- **No persistent state**: No connection pooling or persistent connections to clean up

### Resource Guarantees

| Resource | Cleanup Mechanism | Status |
|----------|-------------------|---------|
| IPython Comm | Jupyter/JupyterHub infrastructure | Automatic on widget disposal |
| Out-of-band socket connections | `async with` context manager | Automatic per-transaction cleanup |
| Secondary kernel connection | JupyterLab kernel manager | Released on widget disposal |
| WebSocket server | Python `websockets` library | Closed when context exits |

**Result**: All communication resources are properly released when the GeoGebra panel is closed, with no resource leaks.

## Security Considerations

### Unix Domain Socket (POSIX)

- **File system permissions** control access to the socket
- Socket created in `/tmp/` with restrictive permissions (default umask)
- Only processes running as the same user can connect
- No network exposure

### TCP WebSocket (Windows)

- **Localhost binding only**: Server binds to `127.0.0.1`, not accessible from network
- **Dynamic port allocation**: OS assigns available port, reducing conflicts
- **Ephemeral connections**: Short-lived connections minimize attack surface
- **No authentication needed**: Local-only communication between trusted processes

### Jupyter Infrastructure

- IPython Comm inherits Jupyter's authentication and authorization
- Token-based access control for WebSocket connections
- HTTPS/WSS support in JupyterHub deployments

## Scalability and Performance

### Connection Overhead

**Out-of-band channel**:
- Connection setup: ~1-5ms (Unix socket) or ~5-10ms (TCP localhost)
- Data transfer: minimal overhead for small JSON payloads
- Connection teardown: immediate

**Trade-off**: Slightly higher per-call overhead vs. persistent connection, but gains:
- No connection pooling or lifecycle management
- No reconnection logic complexity
- Natural cleanup on process termination

### Concurrency

**IPython Comm**: Single-threaded by design (IPython event loop)  
**Out-of-band socket**: Async/await pattern, multiple pending responses possible

**Limitation**: Singleton `GeoGebra` instance per kernel session  
**Rationale**: Avoids complexity of managing multiple Comm targets and socket servers

## Future Enhancements

### Potential Improvements

1. **Connection pooling** for out-of-band socket (reduce setup overhead)
2. **Compression** for large payloads (e.g., Base64-encoded `.ggb` files)
3. **Binary protocol** instead of JSON for performance-critical operations
4. **Multi-instance support** with namespace isolation

### Considered but Rejected

1. **WebRTC Data Channel**: Too complex for local-only communication, browser API limitations
2. **Shared memory**: Not portable across platforms, complex synchronization
3. **HTTP polling**: Higher latency and overhead than WebSocket

## Testing Strategies

### Unit Tests (v0.7.3 - COMPLETE)

**Backend Test Suite** ([tests/](../tests/)):

1. **Parser Tests** ([tests/test_parser.py](../tests/test_parser.py)):
   - 18 test classes, 70+ test methods
   - Dependency graph construction and analysis
   - Topological sorting, generations, reachability analysis
   - Edge cases: empty constructions, single objects, N-ary dependencies
   - Performance tests: 30+ independent objects, linear chains
   - All tests with `cache_enabled=False` for isolation

2. **GeoGebra Applet Tests** ([tests/test_ggbapplet.py](../tests/test_ggbapplet.py)):
   - 6 test classes, 16 test methods
   - Singleton initialization and state management
   - Syntax/semantic validation with mocked applet
   - Object cache management and None-response handling
   - Literal detection (numeric, string, boolean, math functions)
   - Exception handling: `GeoGebraSyntaxError`, `GeoGebraSemanticsError`

3. **Construction File Handling** ([tests/test_construction.py](../tests/test_construction.py)):
   - 5 test classes, 20+ test methods
   - File loading: `.ggb` (ZIP), `.ggb` (Base64), JSON, XML
   - File saving: Round-trip integrity, format preservation
   - Scientific notation handling (implementation-aware testing)

**Coverage**:
- `pytest tests/ --cov=ggblab --cov-report=html`
- Coverage metrics automatically uploaded to Codecov on CI

### Integration Tests (GitHub Actions)

**CI/CD Pipeline** ([.github/workflows/tests.yml](.github/workflows/tests.yml)):

- **Automated on every push** to `main`/`dev` branches
- **Automated on all pull requests**
- **Multi-platform testing**:
  - Ubuntu (Linux), macOS, Windows
  - Python 3.10, 3.11, 3.12
- **30 test matrix combinations** automatically executed
- **Coverage reports** uploaded to Codecov

**Running Tests Locally**:

```bash
# Install test dependencies
pip install -e ".[dev]"
pip install pytest pytest-cov

# Run all tests with coverage
pytest tests/ -v --cov=ggblab --cov-report=html

# Run specific test class
pytest tests/test_parser.py::TestDependencyGraphConstruction -v

# Run with XML output (for CI integration)
pytest tests/ --junitxml=junit.xml --cov=ggblab --cov-report=xml
```

### Browser/Integration Tests (Playwright/Galata)

**Not yet implemented** - planned for v0.8+

- Full browser + kernel workflow validation
- Command execution during idle kernel
- Function calls during long-running cell
- Multiple rapid function calls (concurrency)
- Socket reconnection after backend restart

See [ui-tests/README.md](../ui-tests/README.md) for setup instructions.

### Platform-Specific Tests (via CI)

- **POSIX**: Unix socket creation and permissions tested on Ubuntu/macOS
- **Windows**: TCP WebSocket fallback behavior tested on Windows

---

## Dependency Parser Architecture

### Overview

The `ggb_parser` module (`ggblab/parser.py`) analyzes object relationships in GeoGebra constructions by building directed graphs using NetworkX. It provides two graph representations:

1. **`G` (Full Dependency Graph)**: Complete construction dependencies
2. **`G2` (Simplified Subgraph)**: Minimal construction sequences

### Current Implementation: `parse_subgraph()`

The `parse_subgraph()` method attempts to identify minimal construction sequences by enumerating all possible combinations of root objects and their dependencies.

#### Known Limitations

##### 1. **Combinatorial Explosion (Critical Performance Issue)**

The method generates all possible combinations of root objects:

```python
_paths = []
for __p in (list(chain.from_iterable(combinations(_nodes1, r)
            for r in range(1, len(_nodes1) + 1)))):
    _paths.append(_nodes0 | set(__p))
```

- If there are `n` root objects, this generates $2^n - 1$ potential paths
- With 20+ roots: **~1 million paths** to evaluate
- With 30+ roots: **~1 billion paths** — computation becomes intractable

**Impact**: Large constructions with many independent objects (e.g., multiple input points, parameters) will cause significant performance degradation or hang.

**Workaround**: Limit analysis to constructions with <15 independent root objects.

##### 2. **Infinite Loop Risk**

The iteration condition depends on `_nodes1` being updated:

```python
while _nodes1:
    # ... processing ...
    _nodes1 = _nodes3 - _nodes2 - _nodes1
```

Under certain graph topologies, `_nodes1` may not change, causing the loop to iterate infinitely or until Python resource limits are hit.

##### 3. **Limited Handling of N-ary Dependencies**

The current `match` statement only handles 1-ary and 2-ary dependencies:

```python
match len(_nodes2 - _nodes0):
    case 1:
        # Handle single parent
        self.G2.add_edge(o, n)
    case 2:
        # Handle two parents
        self.G2.add_edge(o1, n)
        self.G2.add_edge(o2, n)
    case _:
        pass  # Silently ignore 3+ parents
```

**Missing**: Constructions where 3+ objects jointly create a dependent object (e.g., a triangle from 3 points, or a polygon from multiple vertices) are not represented in `G2`.

##### 4. **Redundant Neighbor Computation**

Inside the inner loop:

```python
for n1 in _nodes2:
    _n = [set(self.G.neighbors(__n)) for __n in _nodes2]  # Computed every iteration
```

The neighbors list is recalculated on each iteration of `n1`, even though it's independent of `n1`. This is $O(n)$ redundant work per iteration.

##### 5. **Debug Output in Production Code**

```python
print(f"found: '{o}' => '{n}'")
print(f"found: '{o1}', '{o2}' => '{n}'")
```

These debug statements appear in every edge discovery and should be removed for production use or wrapped in a configurable debug flag.

### Recommended Improvements

#### Short Term (v0.7.3)

1. **Remove debug output** and add optional logging:
   ```python
   import logging
   logger = logging.getLogger(__name__)
   logger.debug(f"found: '{o}' => '{n}'")  # Only when debug=True
   ```

2. **Add early termination check** to detect infinite loops:
   ```python
   max_iterations = 100
   iteration_count = 0
   while _nodes1 and iteration_count < max_iterations:
       iteration_count += 1
       # ...
   if iteration_count >= max_iterations:
       logger.warning("parse_subgraph exceeded max iterations; G2 may be incomplete")
   ```

3. **Cache neighbor computation**:
   ```python
   neighbors_cache = {n: set(self.G.neighbors(n)) for n in _nodes2}
   # Then reuse in loop
   ```

4. **Support N-ary dependencies** (3+ parents):
   ```python
   # Instead of match, use a more general approach
   parents = tuple(_nodes2 - _nodes0)
   for parent in parents:
       self.G2.add_edge(parent, n)
   ```

#### Medium Term (v1.0)

**Algorithm replacement**: Adopt a topological sort + reachability pruning approach:

```python
def parse_subgraph_optimized(self):
    """
    Efficient subgraph extraction using topological analysis.
    
    For each node, identify which predecessors are essential by checking
    if removing them disconnects the node from roots.
    
    Time complexity: O(n * (n + m)) instead of O(2^n)
    where n = nodes, m = edges
    """
    self.G2 = nx.DiGraph()
    
    # Topologically sort the graph
    topo_order = list(nx.topological_sort(self.G))
    
    for node in topo_order:
        direct_parents = list(self.G.predecessors(node))
        if not direct_parents:
            continue
        
        # Identify essential parents (those whose removal disconnects from roots)
        essential_parents = []
        for parent in direct_parents:
            # Create a temporary graph without this edge
            G_test = self.G.copy()
            G_test.remove_edge(parent, node)
            
            # Check if node is still reachable from roots
            reachable_from_root = False
            for root in self.roots:
                if nx.has_path(G_test, root, node):
                    reachable_from_root = True
                    break
            
            # If removing this edge disconnects from roots, it's essential
            if not reachable_from_root:
                essential_parents.append(parent)
        
        # Add edges for essential parents
        for parent in essential_parents:
            self.G2.add_edge(parent, node)
```

**Benefits**:
- Polynomial time complexity instead of exponential
- Mathematically clear definition: "essential" = cannot be removed without losing root reachability
- Handles N-ary dependencies naturally
- Deterministic, no infinite loop risk

#### Long Term (v1.5+)

- Support weighted edges (represent "preferred" construction order)
- Interactive subgraph selection (UI-driven)
- Caching of frequently requested subgraphs
- Integration with constraint solving for optimal path identification

### Testing

Current testing coverage for `parse_subgraph()` is minimal. Recommended test cases:

```python
# test_parser.py
def test_parse_subgraph_simple():
    """Single dependency chain: A -> B -> C"""
    # Expected: G2 has edges A->B, B->C
    
def test_parse_subgraph_diamond():
    """Diamond dependency: A,B -> C -> D"""
    # Expected: G2 has edges A->C, B->C, C->D
    
def test_parse_subgraph_binary_tree():
    """Binary tree of dependencies"""
    # Expected: linear time, no combinatorial explosion
    
def test_parse_subgraph_large():
    """Large graph with 50+ nodes"""
    # Expected: completes within 5 seconds
    
def test_parse_subgraph_nary_deps():
    """3+ parents creating single output: A,B,C -> D"""
    # Expected: G2 has edges A->D, B->D, C->D
```

---

## Asyncio Design Challenges in Jupyter

### The Core Problem: Jupyter + Asyncio Impedance Mismatch

Python's `asyncio` module is widely used but has significant limitations in the Jupyter Kernel environment:

1. **IPython Comm Cannot Receive During Cell Execution**
   - While a cell is running, the IPython event loop is blocked
   - Incoming Comm messages cannot be processed until the cell completes
   - This is a fundamental architectural constraint, not a bug

2. **Asyncio Requires Explicit Yield Points**
   - Every `await` statement is a potential yield point where other tasks can run
   - Without explicit `await asyncio.sleep()` calls, **asyncio has no opportunity to switch tasks**
   - Most developers are unaware of this requirement

3. **No Native Event-Based Waiting**
   - `asyncio` lacks a clean way to wait for dictionary updates or queue population
   - Current ggblab implementation uses polling: `while not (_id in self.recv_logs): await asyncio.sleep(0.01)`
   - This is **inefficient and inelegant** compared to event-based systems (e.g., threading.Event)

### Evidence from ggblab/comm.py

**Problematic code pattern**:
```python
async def send_recv(self, msg):
    _id = str(uuid.uuid4())
    self.send(msg)
    
    # Polling loop: check every 10ms if response arrived
    async def wait_for_response():
        while not (_id in self.recv_logs):
            await asyncio.sleep(0.01)  # <-- Explicit yield point required!
    
    await asyncio.wait_for(wait_for_response(), timeout=3.0)
    value = self.recv_logs.pop(_id, None)
```

**Why this is suboptimal**:
- ❌ **Busy-waiting simulation**: Polls every 10ms instead of waiting for an event
- ❌ **Arbitrary sleep time**: 0.01 seconds is a guess; too short = CPU waste, too long = latency
- ❌ **No condition variable**: Threading has `threading.Event` and `threading.Condition`; asyncio has no equivalent
- ❌ **Inefficient for Jupyter**: The Jupyter event loop should be managing concurrency, not application code

**Alternative (if asyncio had better primitives)**:
```python
# This would be cleaner (but asyncio doesn't provide it natively)
response_event = asyncio.Event()

def on_response_received(id):
    response_event.set()

await asyncio.wait_for(response_event.wait(), timeout=3.0)
```

### Why This Matters for Language Selection

This complexity reveals why **TypeScript/Node.js backend might have been technically superior**:

| Aspect | Python asyncio | Node.js async/await |
|--------|---|---|
| **Event loop** | Complex, user must manage | Simple, built-in, always running |
| **Waiting for events** | Manual polling required | `async/await` + Promise chains |
| **Blocking during cell execution** | Blocks Jupyter event loop | Would block Node.js event loop (similar issue) |
| **Learning curve** | High; requires deep understanding | Medium; familiar to web developers |
| **Operational context** | Not standard in Jupyter | Even less standard in Jupyter |

**Key insight**: The problem isn't Python's asyncio per se—it's that **any framework must bridge the gap between Jupyter's execution model and concurrent communication**. TypeScript wouldn't solve this; it just moves the problem to a less-familiar runtime.

### Deployment Reality: Why Python Wins Despite Complexity

Despite asyncio's technical shortcomings, Python remains the better choice because:

1. **Jupyter already assumes Python**: Most institutional deployments have Python; Node.js doesn't
2. **Users expect Python**: ggblab students are already Python programmers
3. **Complexity is hidden**: Users don't see `comm.py`; they call `await ggb.command()`
4. **Works well enough**: Even with polling, the 10ms cycle is imperceptible to users

The lesson: **Operational constraints (kernel availability) trump technical elegance (language features)**.

### Recommendations for Future Work

#### Current Implementation: Best Practical Solution

The current implementation using polling with explicit `await asyncio.sleep(0.01)` **is the best practical solution** given Jupyter's constraints:

**Why asyncio.Event doesn't solve the problem**:
- `asyncio.Event` has been tested extensively but does not circumvent the IPython Comm limitation
- The issue is not waiting mechanism (Event vs polling)—it's that IPython's event loop itself is blocked during cell execution
- When a cell runs, IPython's event loop cannot process **any** incoming Comm messages, regardless of how elegantly the backend waits
- Polling is necessary because Comm messages may arrive via the out-of-band socket at unpredictable times

**Why threading doesn't work**:
- Threading would require the Comm handler to run in a different thread, creating race conditions
- IPython Comm operations are not thread-safe; they assume single-threaded kernel execution
- Refactoring to thread-safe Comm would require changes to IPython itself

**Current design is robust**:
- ✅ Polling with 0.01s sleep is imperceptible to users (10ms is below human reaction time)
- ✅ Timeout-based fallback (3 seconds) is sufficient for interactive operations
- ✅ Event queue (`recv_events`) properly captures async error events
- ✅ Dual-channel architecture elegantly sidesteps the IPython Comm blocking limitation

**Conclusion**: The current implementation is **not a compromise**—it's the **optimal solution** given the architectural constraints of Jupyter and IPython Comm.

#### Global Scope Buffer Requirement

A critical constraint often missed: asyncio data exchange buffers **must be class variables (global scope)**, not instance variables.

**Current implementation** (ggblab/comm.py):
```python
class ggb_comm:
    # These MUST be at class scope, not instance scope
    recv_logs = {}          # Response storage by message ID
    recv_events = queue.Queue()  # Error event queue
    logs = []               # Diagnostic logs
```

**Why class scope is required**:

1. **Multiple async tasks access the same buffers**:
   - `client_handle()` (server connection handler) populates `recv_logs` and `recv_events`
   - `send_recv()` (command sender) reads from `recv_logs` and `recv_events`
   - Both run concurrently in the same event loop

2. **Async task isolation prevents instance variable sharing**:
   - Each `await` point creates a suspension boundary
   - If buffers were instance variables, different async tasks would be looking at different dictionaries
   - This breaks message correlation

3. **Event loop singleton**:
   - There is one event loop per Python kernel process
   - `ggb_comm` is instantiated once per kernel
   - Putting buffers at class scope ensures they persist across all `await` points and async task switches

**Example of what FAILS with instance variables**:
```python
class ggb_comm_broken:
    def __init__(self):
        self.recv_logs = {}  # ❌ Instance variable
        self.recv_events = queue.Queue()  # ❌ Instance variable

    async def send_recv(self, msg):
        _id = str(uuid.uuid4())
        self.send(msg)
        
        # This checks a DIFFERENT recv_logs than client_handle() populates!
        while not (_id in self.recv_logs):  # ❌ Sees empty dict
            await asyncio.sleep(0.01)
        
        # Message ID never arrives because it went to a different dictionary
```

**Why this fails**:
- Instance variables are created per object instance
- `self.recv_logs` refers to the instance's dictionary
- `client_handle()` may be running in a different async task context
- No guarantee that `send_recv()`'s `self` refers to the same object as `client_handle()`'s `self`
- Even if it does, the timing of async task scheduling can cause data races

**Proper design with class variables**:
```python
class ggb_comm:
    # Class variables: shared across all async tasks
    recv_logs = {}          # All tasks see the same dict
    recv_events = queue.Queue()  # All tasks see the same queue
    
    async def send_recv(self, msg):
        _id = str(uuid.uuid4())
        self.send(msg)
        
        # This checks THE SAME recv_logs that client_handle() populates
        while not (_id in self.recv_logs):  # ✅ Sees shared dict
            await asyncio.sleep(0.01)
```

**Reference**:
- [Jupyter Community Forum: Frontend to Kernel Callback](https://discourse.jupyter.org/t/frontent-to-kernel-callback/1666)
- This constraint is documented in the discussion but often overlooked by developers new to asyncio

#### No Near-Term Refactoring Recommended

Attempts to replace polling with `asyncio.Event`, `asyncio.Condition`, or other primitives have proven unsuccessful because they don't address the root cause (IPython event loop blocking during cell execution). The current implementation should remain stable.

---

#### Long-Term: Jupyter Kernel Architecture Evolution

True improvement would require changes at the Jupyter/IPython level:

1. **IPython Comm receives during cell execution**: Requires IPython architecture redesign (unlikely)
2. **Async-first kernel**: Redesign kernel messaging to be fully asynchronous (ambitious, long-term)
3. **Separate kernel-side event loop**: Run communication on a different event loop than cell execution (complex isolation required)

These are beyond the scope of ggblab and would require Jupyter/IPython community effort.

---

## Design Decision: Backend Language Selection (Python vs. TypeScript)

### Context: Why Python for `ggb_comm.py`?

The backend communication handler (`ggblab/comm.py`) is implemented in **Python**, even though the frontend is **TypeScript/React**. This decision involves trade-offs worth documenting for future maintainers.

### Option Analysis

#### Option A: Python Backend (Current Choice)

**Advantages**:
- ✅ **Kernel ecosystem**: Jupyter kernels for Python are ubiquitous; most Jupyter environments have Python available
- ✅ **Asyncio maturity**: Python's `asyncio` is well-documented and battle-tested for educational purposes
- ✅ **Single language for data science stack**: Scientific computing typically uses Python (NumPy, SciPy, SymPy, etc.)
- ✅ **Wider adoption**: Python dominates STEM education; ggblab students are already Python programmers
- ✅ **Package distribution**: PyPI distribution is straightforward; pip install handles versioning

**Disadvantages**:
- ❌ **Runtime dependency**: Python must be installed and available in the Jupyter environment
- ❌ **Version management**: Requires Python 3.10+; older environments may not have it
- ❌ **Kernel startup overhead**: Python kernel startup is slower than lightweight runtimes

#### Option B: TypeScript/Node.js Backend

**Hypothetical advantages** if implemented:
- ✅ **Single language**: Frontend and backend in same language (DRY principle)
- ✅ **Code sharing**: Message types, validation logic could be reused via TypeScript interfaces
- ✅ **Lighter runtime**: Node.js faster startup than Python
- ✅ **NPM distribution**: Familiar to JavaScript ecosystem

**Critical disadvantages**:
- ❌ **Kernel availability**: Jupyter Node.js kernels are **not standard**. Most Jupyter installations lack Node.js runtime
- ❌ **Deployment complexity**: Users would need to install Node.js separately or use alternative kernels (like `ijavascript` or `jp-ts`)
- ❌ **Educational friction**: Students expect Python in Jupyter; adding Node.js requirement increases setup complexity
- ❌ **Version parity problem**: Frontend (TypeScript) and backend (Node.js) would be separate versioned products with sync requirements
- ❌ **Kernel infrastructure**: Standard Jupyter assumes Python kernel; Node.js kernels require additional setup
- ❌ **IPython Comm**: While IPython Comm is language-agnostic, Node.js kernels have variable support quality

### Operational Constraints

#### Jupyter Kernel Availability

**Current reality**:
- Python kernel: **Always present** in any Jupyter installation (assumption: Jupyter >= 4.0)
- Node.js kernel: **Optional**, requires separate installation and configuration
- R kernel: **Common** but optional
- Julia kernel: **Rare**, requires additional setup

**Implication**: ggblab's Python backend ensures the extension works out-of-the-box. Users don't need to think about runtime selection.

#### Deployment Context

**JupyterHub in Educational Settings**:
- Sysadmins control what kernels are available
- Adding Node.js requirement would require admin approval and installation
- Creates additional maintenance burden on institutions

**Cloud Deployments** (Google Colab, JupyterHub SaaS):
- Colab provides Python by default; Node.js not available
- Enterprise JupyterHub usually provides Python only (Typescript/Node optional)
- Python backend maximizes compatibility

### The Communication Stack

Despite the backend being Python, the communication stack is **language-neutral**:

```
Frontend (TypeScript)  ←→  IPython Comm (JSON messages)  ←→  Backend (Python async)
    ↓                                                           ↓
GeoGebra API                                          Kernel + socket server
    ↓                                                           ↓
    └─────── Out-of-band socket (WebSocket/Unix) ──────────────┘
                   (Protocol-agnostic transport)
```

This design means:
- ✅ Frontend can be written in any language (TypeScript chosen for React ecosystem)
- ✅ Backend can be written in any Jupyter-supported language (Python chosen for ubiquity)
- ✅ Communication protocol is language-independent (JSON + WebSocket)

### Lessons Learned

**Key insight**: Tight coupling of frontend and backend languages (TypeScript for both) is **not justified** when:
1. The kernel availability determines deployment success more than implementation language
2. The target audience (Python programmers) expects Python
3. The communication protocol is already language-agnostic
4. Code sharing benefits are minimal (message types are simple JSON, validation logic is kernel-specific)

**Recommendation for future changes**:
- Keep frontend in TypeScript (React ecosystem is mature; switching gains nothing)
- Keep backend in Python (addresses operational constraints; switching to Node.js creates problems)
- If non-Python kernel support is desired, implement additional *kernels* (e.g., Julia, R) via separate language-specific packages, not by switching the reference implementation

### TypeScript Backend: When It Could Work

TypeScript backend would be viable **only if**:
1. **Standard Node.js kernel** emerges as Jupyter standard (unlikely)
2. **Deployment targets only advanced users** who already manage Node.js (educational loss)
3. **Code sharing between frontend and backend is critical** (currently minimal benefit)

None of these conditions are currently met, so Python remains the better choice.

---

## Non-Python Kernel Support (Julia, R, etc.)

### Protocol Portability

The ggblab communication architecture is **language-agnostic** at the protocol level:

- ✅ **IPython Comm**: Supported by any Jupyter kernel (uses JSON messages)
- ✅ **WebSocket/Unix Socket**: Language-independent transport (any language can open sockets)
- ✅ **Message Format**: JSON-based, not Python-specific

However, implementing language-specific client libraries requires addressing several challenges.

### Critical Implementation Notes for Non-Python Kernels

#### 1. Asynchronous Execution Model Must Match

**Challenge**: Different languages have different async patterns.

| Aspect | Python | Julia | R |
|--------|--------|-------|---|
| **Async syntax** | `async/await` | `@async` / `Task` | `future` / promise-like |
| **Blocking behavior** | `await` blocks on Awaitable | `wait()` on Task | `resolve()` on future |
| **Event loop** | `asyncio.run()` | `@async` tasks | Single-threaded |
| **Multiple concurrent operations** | Multiple `await` in same scope | Multiple tasks in same scope | Parallel evaluation or callbacks |

**Recommendation**: Implement `send_recv()` with the language's native async primitives, not by wrapping Python's asyncio.

**Example (Julia pseudocode)**:
```julia
async function send_recv(msg::Dict)::Dict
    id = uuid4()
    put!(comm_channel, merge(msg, Dict("id" => id)))
    
    # Wait for response with matching id
    while true
        response = take!(response_channel)  # Blocking wait
        if response["id"] == id
            return response
        end
    end
end
```

#### 2. Message ID Correlation

**Requirement**: Backend and frontend must exchange `id` fields to correlate responses with requests.

**Format** (JSON):
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "command",
    "payload": "A=(0,0)",
    ...
}
```

All languages must:
1. Generate a unique `id` (UUID/UUID4) for each `send_recv()` call
2. Include `id` in the Comm message to frontend
3. Receive response with matching `id` via out-of-band socket
4. Match response by `id` before returning to caller

**Error case**: If response arrives with wrong `id`, queue it and continue waiting. This handles concurrent requests.

#### 3. Out-of-Band Socket Connection (Language-Specific)

**Python**: Uses `asyncio` WebSocket client (see `ggblab/comm.py`)

**Julia**: Use Julia's WebSocket library:
```julia
using WebSockets
ws = WebSocket("ws://localhost:$port")  # TCP on Windows
# or
ws = connect(socket_path)  # Unix socket on POSIX (if library supports)
```

**R**: Use R's WebSocket library:
```r
library(websocket)
ws <- WebSocket$new("ws://localhost:port")
```

**Critical**: Each `send_recv()` must open a **separate, transient connection** for that specific request. Do NOT maintain a persistent connection.

#### 4. IPython Comm Target Registration

**Requirement**: Register a Comm target handler to receive commands from frontend.

The Comm target name must be `ggblab-comm` (hardcoded in frontend).

**Python implementation** (reference):
```python
def comm_handler(comm, open_msg):
    @comm.on_msg
    def _recv(msg):
        content = msg['content']['data']
        # Process command, store response for out-of-band delivery
```

**Julia equivalent**:
```julia
# Julia kernels expose Comm via kernel API
kernel_comm = kernel.comm
comm_handler = message -> begin
    # Process message
end
register_comm("ggblab-comm", comm_handler)
```

**R equivalent**:
```r
# R kernels may use IRkernel package
IRkernel::register_comm("ggblab-comm", function(msg) {
    # Process message
})
```

**Note**: Exact API varies by language. Consult Jupyter kernel documentation for your language.

#### 5. Object Cache Management (Language-Dependent)

**Challenge**: Python uses a dictionary; other languages may prefer different data structures.

**Requirements** (language-independent):
- Store GeoGebra object names and metadata
- Refresh from applet via `evalCommand("GetValue('_json')")`
- Check object existence before sending commands (optional but recommended)

**Python reference**:
```python
self._applet_objects = {}  # Dict[name, metadata]

async def refresh_object_cache(self):
    json_str = await self.function("getBase64", [])
    # Parse and store
    self._applet_objects = parse_geogebra_json(json_str)
```

#### 6. Error Handling (Critical Differences)

**Key constraint**: GeoGebra sends **NO explicit error responses** for invalid commands.

**Error detection mechanisms** (all languages):
1. **Timeout after 3 seconds**: Command was rejected or crashed GeoGebra
2. **Error dialog events**: Captured by frontend and queued in `recv_events`
3. **Response with no payload**: May indicate error (GeoGebra silently failed)

**Error handling pattern** (pseudo-code):
```
try:
    result = send_recv(command)
catch TimeoutError:
    # Command rejected or GeoGebra crashed
    check recv_events for error dialog
    if error_event found:
        raise GeoGebraAppletError(error_event.message)
    else:
        raise TimeoutError("No response from GeoGebra")
```

**Recommendation**: Implement error classes isomorphic to Python's:
- `GeoGebraError` (base)
  - `GeoGebraCommandError` (pre-flight)
    - `GeoGebraSyntaxError`
    - `GeoGebraSemanticsError`
  - `GeoGebraAppletError` (runtime)

#### 7. Configuration and Initialization

**Requirement**: The kernel must receive communication settings (Comm target, socket path/port) from the frontend before issuing commands.

**Currently**: Python uses `GeoGebra().init()` which:
1. Sets up Comm handler for `ggblab-comm`
2. Starts out-of-band socket server
3. Triggers frontend command `ggblab:create` with socket path/port
4. Waits for frontend to confirm connection before returning

**For other languages**: Implement similar initialization:
- Register Comm target
- Start socket server
- Store path/port for `send_recv()` to use
- Confirm ready before accepting commands

**Example (Julia)**:
```julia
mutable struct GeoGebra
    comm_channel::Channel
    response_channel::Channel
    socket_path::String
    socket_port::Int
    
    function init()
        # Register Comm, start socket, trigger frontend
        # Return instance
    end
end
```

### Recommended Implementation Path

1. **Document the protocol thoroughly** (beyond this section):
   - JSON message formats
   - Comm message structure
   - Out-of-band socket protocol
   - Complete example exchange (command → response)

2. **Provide reference implementations** for a second language (e.g., Julia):
   - Complete `GGBLab.jl` package with same interface as Python
   - Include tests and examples
   - Keep parity with Python version

3. **Version the protocol**:
   - Add protocol version field to messages
   - Allow graceful degradation if languages use different versions
   - Document backward compatibility guarantees

4. **Validate with a non-Python kernel**:
   - Implement Julia support end-to-end
   - Verify all edge cases work (timeouts, error events, etc.)
   - Document known limitations per language

### Summary

Non-Python kernel support is **technically feasible** but requires:
- Careful async/await pattern translation
- Proper UUID-based message ID correlation
- Robust timeout and error event handling
- Language-specific Comm registration
- Comprehensive protocol documentation

The core communication design (IPython Comm + out-of-band socket) poses **no fundamental barriers** to non-Python languages. The effort is primarily in documentation and reference implementation.

---

## References

- [IPython Comm documentation](https://ipython.readthedocs.io/en/stable/development/messaging.html#custom-messages)
- [Jupyter/JupyterHub WebSocket handling](https://jupyterhub.readthedocs.io/en/stable/)
- [Unix Domain Sockets (Python websockets)](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html#unix-domain-sockets)
- [GeoGebra Apps API](https://geogebra.github.io/docs/reference/en/GeoGebra_Apps_API/)
- [NetworkX Documentation](https://networkx.org/documentation/stable/)
- [Topological Sorting](https://en.wikipedia.org/wiki/Topological_sorting)
