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
            self.recv_logs[_id] = _data['payload']  # Store response keyed by message ID
    finally:
        self.clients.remove(client_id)
```

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

## References

- [IPython Comm documentation](https://ipython.readthedocs.io/en/stable/development/messaging.html#custom-messages)
- [Jupyter/JupyterHub WebSocket handling](https://jupyterhub.readthedocs.io/en/stable/)
- [Unix Domain Sockets (Python websockets)](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html#unix-domain-sockets)
- [GeoGebra Apps API](https://geogebra.github.io/docs/reference/en/GeoGebra_Apps_API/)
- [NetworkX Documentation](https://networkx.org/documentation/stable/)
- [Topological Sorting](https://en.wikipedia.org/wiki/Topological_sorting)
