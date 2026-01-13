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

## Data Flow Diagrams

### Normal Command Execution (Primary Channel)

```
Python Kernel                    Frontend (Browser)
     |                                  |
     |  1. command("A=(0,0)")           |
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

## Implementation Details

### Backend: `ggb_comm` (ggblab/comm.py)

**Responsibilities**:
- Start Unix socket server (POSIX) or TCP WebSocket server (Windows)
- Register IPython Comm target (`test3` by default)
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
            self.recv_logs[_id] = _data['payload']  # Store response keyed by message ID
    finally:
        self.clients.remove(client_id)
```

### Frontend: Widget Connection Logic (src/widget.tsx)

**Comm Setup**:
```typescript
const comm = kernel.createComm(props.commTarget || 'test');
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
**Status**: Basic (timeout-based)

The out-of-band channel operates independently and has limited error detection:

#### Timeout Model

The out-of-band socket has a **3-second timeout**:

```python
# In ggblab/comm.py send_recv()
try:
    response = await asyncio.wait_for(
        future,  # Waiting for response to arrive
        timeout=3.0  # 3-second timeout
    )
except asyncio.TimeoutError:
    raise TimeoutError(f"Out-of-band response timeout for message id={msg_id}")
```

If no response arrives within 3 seconds, a `TimeoutError` exception is raised in Python code:

```python
try:
    label = await applet.evalCommand("GetValue(a)")
except TimeoutError:
    print("GeoGebra did not respond within 3 seconds")
```

#### GeoGebra API Constraint: No Explicit Error Responses

**Critical limitation**: The GeoGebra API does NOT provide explicit error response codes or callbacks.

This means:
- When a command fails (e.g., invalid syntax, reference to non-existent object), GeoGebra does not send an error response via the out-of-band socket
- No error codes, error messages, or structured error data are returned
- The only error signal is **timeout after 3 seconds**

**Example**:
```python
# This will timeout, not return an error message
try:
    result = await applet.evalCommand("DeleteObject(NonExistent)")
except TimeoutError:
    print("GeoGebra rejected the command (no explicit error returned)")
```

#### Dialog-Based Error Signaling

GeoGebra communicates errors primarily through **native UI dialogs** (popup windows):

- When a command fails, GeoGebra displays an error dialog in the browser
- ggblab's frontend widget **hooks GeoGebra's dialog events** and forwards them via the primary IPython Comm channel
- This allows Python code to detect dialog-based errors:

```python
# Pseudo-code: Dialog event signaled via Comm
message = await applet.getNextEvent()  # Receives dialog event
if message['type'] == 'dialog':
    print(f"GeoGebra error: {message['message']}")
```

#### Error Handling Summary

| Channel | Error Detection | Status | Recovery |
|---------|-----------------|--------|----------|
| IPython Comm | Jupyter infrastructure | Automatic | Jupyter handles reconnection |
| Out-of-band socket | 3-sec timeout | Basic | `TimeoutError` exception to Python |
| GeoGebra API | Dialog popups | External dependency | Frontend monitors dialog events |

**Current Limitation**: Non-dialog errors result in timeout with minimal context information.

### Future Error Handling Improvements (v0.8.x)

To improve error handling on the out-of-band channel:

1. **Timeout Detection and Python Exceptions**
   - Convert timeout to Python exceptions with context (command, timestamp)
   - Propagate exception details to user with stack trace

2. **Custom Timeout Configuration**
   - Allow `GeoGebra(timeout=5.0)` to set custom timeout per applet instance
   - Allow `evalCommand(..., timeout=10.0)` for command-specific timeout

3. **Dialog Message Extraction**
   - Parse GeoGebra dialog content for error details
   - Return structured error information (error code, message, object reference)

4. **Retry Logic for Transient Errors**
   - Distinguish transient (network, timing) vs. permanent (API) errors
   - Implement exponential backoff for transient failures

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

### Unit Tests

- Mock IPython Comm: Test message dispatch and response handling
- Mock socket server: Test out-of-band delivery independent of Comm

### Integration Tests

- Playwright/Galata: Full browser + kernel workflow
- Test scenarios:
  - Command execution during idle kernel
  - Function calls during long-running cell
  - Multiple rapid function calls (concurrency)
  - Socket reconnection after backend restart

### Platform-Specific Tests

- POSIX: Verify Unix socket creation and permissions
- Windows: Verify TCP WebSocket fallback behavior

## References

- [IPython Comm documentation](https://ipython.readthedocs.io/en/stable/development/messaging.html#custom-messages)
- [Jupyter/JupyterHub WebSocket handling](https://jupyterhub.readthedocs.io/en/stable/)
- [Unix Domain Sockets (Python websockets)](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html#unix-domain-sockets)
- [GeoGebra Apps API](https://geogebra.github.io/docs/reference/en/GeoGebra_Apps_API/)
