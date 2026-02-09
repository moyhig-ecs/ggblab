# Async Widget Monitoring in Jupyter: Best Practices

## Overview

Reliable widget monitoring in Jupyter environments requires understanding how async/await works, particularly the critical role of `asyncio.sleep()`. This guide explains the polling pattern and why it's the recommended approach for ggblab.

## The Polling Pattern: Recommended Approach

### Core Concept

Monitor widget values in a continuous async loop, checking for changes at regular intervals:

```python
import asyncio
import ipywidgets as widgets
from IPython.display import display

# Create widgets
slider = widgets.IntSlider(value=0, min=0, max=100, description='Value:')
output = widgets.Output()
display(slider, output)

async def monitor_slider():
    """Monitor slider value and execute processing when it changes."""
    with output:
        print("✓ Monitor started")
    
    last_value = slider.value
    
    while True:
        current_value = slider.value
        
        # Detect value change
        if current_value != last_value:
            with output:
                output.clear_output(wait=True)
                print(f"⏳ Processing: {current_value}")
            
            # Perform expensive computation here
            # await heavy_computation(current_value)
            
            with output:
                print(f"✓ Complete: {current_value}")
            
            last_value = current_value
        
        # Critical: yield control to event loop
        await asyncio.sleep(0.1)

# Start monitoring
task = asyncio.create_task(monitor_slider())

# Stop monitoring: task.cancel()
```

## Understanding asyncio.sleep()

### Two Critical Functions of `asyncio.sleep()`

#### 1. **Time-Based Waiting** (Obvious)

```python
await asyncio.sleep(0.1)  # Pause for 100 milliseconds
```

Suspends the current task for the specified duration.

#### 2. **Event Loop Yield** (Essential)

```python
while True:
    # Do some work
    process_data()
    
    # CRITICAL: Yield control back to the event loop
    await asyncio.sleep(0)  # Even with 0 seconds, this yields control
```

When you `await asyncio.sleep()`, you **yield control back to the event loop**, allowing other tasks to run.

### Why This Matters

Without `await asyncio.sleep()`, your task monopolizes the event loop:

```python
# ❌ BLOCKS THE EVENT LOOP
async def bad_monitor():
    while True:
        current_value = slider.value  # Tight loop, no yield
        # Other tasks STARVE and never get CPU time
        # Jupyter responsiveness FREEZES

# ✅ YIELDS CONTROL PROPERLY
async def good_monitor():
    while True:
        current_value = slider.value
        await asyncio.sleep(0.1)  # Yields control, other tasks can run
```

### Event Loop Operation

```
Timeline with proper yielding:
┌─────────────────────────────────────────────────────────────┐
│ Event Loop                                                  │
├─────────────────────────────────────────────────────────────┤
│ [Task A: do work] ─→ await sleep(0.1) ─→                  │
│                                        [Task B: run] ─→    │
│                                                    await ─→ │
│ [Task A: resume] ─→ do work ─→ await sleep(0.1) ─→       │
│                                                    [Task B]  │
└─────────────────────────────────────────────────────────────┘

All tasks get CPU time because each yields with await asyncio.sleep()
```

### What `asyncio.sleep()` Actually Does

When you write:

```python
await asyncio.sleep(0.1)
```

The runtime:

1. **Suspends** the current task (saves its state)
2. **Removes** it from the run queue temporarily
3. **Runs** other waiting tasks
4. **Schedules** this task to resume after 0.1 seconds
5. **Resumes** this task when the time elapses

**Key insight**: Other tasks run while this one sleeps!

## Polling Interval Selection

Choose your `asyncio.sleep()` duration based on responsiveness needs:

### Responsiveness vs. CPU Load Trade-off

```python
# Ultra-high responsiveness (web-scale real-time)
await asyncio.sleep(0.01)   # 10ms → 100 checks/sec
# ⚠️ High CPU usage, unnecessary for most UI interactions

# High responsiveness (recommended for interactive widgets)
await asyncio.sleep(0.05)   # 50ms → 20 checks/sec
# ✅ Good balance for slider/button interactions

# Balanced (recommended for most use cases)
await asyncio.sleep(0.1)    # 100ms → 10 checks/sec
# ✅ Default choice - responsive yet CPU-efficient

# Low CPU overhead (background monitoring)
await asyncio.sleep(0.5)    # 500ms → 2 checks/sec
# ✅ Good for slow-changing values, background tasks

# Background task (minimal CPU)
await asyncio.sleep(1.0)    # 1s → 1 check/sec
# ✅ For very infrequent monitoring
```

### Widget Type Guidance

| Widget Type | Suggested Interval | Reasoning |
|-------------|-------------------|-----------|
| **Slider/Numeric Input** | 0.05-0.1s | User manipulation is fast |
| **Dropdown/Selection** | 0.1-0.2s | User actions are discrete |
| **File uploads** | 0.2-0.5s | Infrequent state changes |
| **Background sync** | 0.5-1.0s | Minimal user interaction |

## Complete Production-Ready Example

```python
"""
Production-ready async widget monitoring with ggblab integration.

Key features:
- Proper context management for output widget
- Error handling and recovery
- Clean startup and shutdown
- CPU-efficient polling interval
"""

import asyncio
import ipywidgets as widgets
from IPython.display import display
from typing import Optional, Callable, Any

class WidgetMonitor:
    """
    Monitors an ipywidget slider and executes async processing.
    
    Features:
    - Reliable across all Jupyter environments
    - Proper resource cleanup
    - Structured logging via output widget
    - Customizable polling interval
    - Graceful error handling
    """
    
    def __init__(
        self,
        slider: widgets.IntSlider,
        output: widgets.Output,
        polling_interval: float = 0.1,
        processor: Optional[Callable[[int], Any]] = None
    ):
        """
        Initialize the monitor.
        
        Args:
            slider: IntSlider widget to monitor
            output: Output widget for displaying status
            polling_interval: Time between checks in seconds
                - Default 0.1s (100ms) is suitable for most interactive widgets
                - Smaller values: more responsive but higher CPU usage
                - Larger values: lower CPU usage but slower detection
            processor: Optional async function to call on value change
        """
        self.slider = slider
        self.output = output
        self.polling_interval = polling_interval
        self.processor = processor
        self.task: Optional[asyncio.Task] = None
        self._last_value = slider.value
    
    async def _heavy_computation(self, value: int) -> str:
        """
        Simulate expensive computation (e.g., AI inference, data processing).
        
        In real usage, replace with actual async work.
        """
        # Custom processor if provided
        if self.processor:
            return await self.processor(value)
        
        # Default: simulate work
        await asyncio.sleep(1)
        return f"Processed value {value}"
    
    async def monitor(self) -> None:
        """
        Main monitoring loop.
        
        Continuously checks slider value at polling_interval.
        Yields control to event loop on each iteration via asyncio.sleep().
        This allows other Jupyter operations and tasks to run.
        """
        with self.output:
            print("✓ Monitor started")
            print(f"  Polling interval: {self.polling_interval}s")
        
        try:
            while True:
                # Read current value without blocking
                current_value = self.slider.value
                
                # Detect change
                if current_value != self._last_value:
                    with self.output:
                        self.output.clear_output(wait=True)
                        print(f"⏳ Processing slider value: {current_value}")
                    
                    try:
                        # Execute computation
                        result = await self._heavy_computation(current_value)
                        
                        # Display result
                        with self.output:
                            print(f"✓ Complete: {result}")
                    
                    except asyncio.CancelledError:
                        raise  # Propagate cancellation
                    
                    except Exception as e:
                        with self.output:
                            print(f"✗ Error: {type(e).__name__}: {e}")
                        console.error(f"Processing error: {e}")
                    
                    self._last_value = current_value
                
                # CRITICAL: Yield control to event loop
                # Without this, other tasks would starve and Jupyter would freeze
                # Even waiting 0.1s is dominated by this yield behavior
                await asyncio.sleep(self.polling_interval)
        
        except asyncio.CancelledError:
            with self.output:
                print("⚠ Monitor stopped")
            raise
    
    def start(self) -> None:
        """Start monitoring in a background task."""
        if self.task is not None:
            raise RuntimeError("Monitor already running")
        
        self.task = asyncio.create_task(self.monitor())
    
    def stop(self) -> None:
        """Stop monitoring."""
        if self.task is not None:
            self.task.cancel()
            self.task = None

# Usage
slider = widgets.IntSlider(value=0, min=0, max=100, description='Value:')
output = widgets.Output()
display(slider, output)

# Create and start monitor with 100ms polling interval
monitor = WidgetMonitor(slider, output, polling_interval=0.1)
monitor.start()

# To stop:
# monitor.stop()
```

## Why Event-Driven Approach (`observe`) Is Less Reliable

### The Problem

```python
# ❌ Unreliable across environments
def on_slider_change(change):
    with output:
        print(f"Changed to: {change['new']}")

slider.observe(on_slider_change, names='value')
```

**Issues:**

1. **Comm Protocol Dependency**: Relies on Jupyter WebSocket communication
   - VS Code: Often unstable
   - JupyterLab: Generally reliable
   - Classic Notebook: Intermittent issues

2. **Context Management**: Handler executes in unpredictable context
   - Different thread pool or callback context
   - `with output:` may not capture correctly
   - Silent failures (no error messages)

3. **No Guaranteed Execution**: If Comm protocol fails, handler never runs
   - Silent failure: event is lost
   - No indication to user something is wrong

### Comparison Table

| Aspect | Event-Driven (`observe`) | Polling |
|--------|------------------------|---------|
| **Reliability** | Environment-dependent | Guaranteed |
| **Context Safety** | Uncertain | Guaranteed |
| **CPU Usage** | Minimal (reactive) | Low (configurable) |
| **Debugging** | Difficult (silent failures) | Easy (print works) |
| **Portability** | Low | High |
| **Error Visibility** | Hidden | Visible |

## Integration with ggblab

### Monitoring GeoGebra Widget Changes

```python
from ggblab import GeoGebraWidget
import asyncio
import ipywidgets as widgets
from IPython.display import display

# GeoGebra widget
ggb = GeoGebraWidget()

# Control slider
angle_slider = widgets.FloatSlider(
    value=45, min=0, max=360,
    step=1, description='Angle:'
)

output = widgets.Output()
display(ggb, angle_slider, output)

async def sync_geometry():
    """
    Monitor slider and sync GeoGebra geometry.
    
    Uses polling pattern because:
    1. Works reliably in all Jupyter environments
    2. GeoGebra updates require multiple operations
    3. Output context is guaranteed for status messages
    4. Easy to debug and extend
    """
    with output:
        print("✓ Geometry synchronization started")
    
    last_angle = -1
    
    try:
        while True:
            current_angle = angle_slider.value
            
            if current_angle != last_angle:
                with output:
                    output.clear_output(wait=True)
                    print(f"⏳ Updating angle to {current_angle}°")
                
                # Update GeoGebra (if API supports it)
                try:
                    ggb.set_value('angle', current_angle)
                    with output:
                        print(f"✓ Angle set to {current_angle}°")
                except Exception as e:
                    with output:
                        print(f"✗ Failed to update: {e}")
                
                last_angle = current_angle
            
            # Yield control - allows Jupyter responsiveness
            # 0.1s interval balances responsiveness and CPU usage
            await asyncio.sleep(0.1)
    
    except asyncio.CancelledError:
        with output:
            print("⚠ Synchronization stopped")
        raise

# Start synchronization
sync_task = asyncio.create_task(sync_geometry())

# Stop when done:
# sync_task.cancel()
```

## Key Takeaways

### Remember

1. **`asyncio.sleep()` has two purposes:**
   - ✅ Wait for a specified duration (obvious)
   - ✅ **Yield control to event loop** (critical, often forgotten)

2. **Without `await asyncio.sleep()`:**
   - The event loop cannot switch to other tasks
   - Jupyter UI becomes unresponsive
   - Other kernel operations starve

3. **Polling Pattern Advantages:**
   - Works reliably everywhere
   - Simple to understand and debug
   - Output context guaranteed
   - CPU usage controlled via interval

4. **Choosing Polling Interval:**
   - 0.05-0.1s: Interactive widgets (sliders, inputs)
   - 0.1-0.5s: Discrete widgets (dropdowns, buttons)
   - 0.5-1.0s: Background monitoring

### Best Practice for ggblab

```python
# ✅ RECOMMENDED: Polling pattern
async def monitor_and_sync():
    last_value = -1
    while True:
        current_value = widget.value
        if current_value != last_value:
            # Process change
            last_value = current_value
        await asyncio.sleep(0.1)  # Yield + wait

task = asyncio.create_task(monitor_and_sync())
```

---

## References

- [Python asyncio Documentation](https://docs.python.org/3/library/asyncio.html)
- [Asyncio Sleep Behavior](https://docs.python.org/3/library/asyncio-task.html#asyncio.sleep)
- [ipywidgets Documentation](https://ipywidgets.readthedocs.io/)
- [Jupyter Architecture](https://jupyter.org/index.html)
