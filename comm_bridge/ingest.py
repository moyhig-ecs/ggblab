"""Shared ingest loop implementation for comm_bridge.

This module provides `IngestLoop` which encapsulates the websocket/unix
socket server used to receive out-of-band messages and update the
parent `OOB_Server`'s shared state. The implementation mirrors the
behaviour previously embedded in `comm_bridge/OOB_Server.py` to ease
refactoring and future reuse.
"""
import asyncio
import json
import os
import socket as _socket
import tempfile
import time
from typing import Any, Optional

from websockets.asyncio.server import serve, unix_serve


class IngestLoop:
    """Ingest-side WebSocket handler implementation.

    This class contains the actual ingestion loop formerly implemented on
    `OOB_Server._ingest_ws_handler`. It operates on `self.server` to update
    `shared_objects` and enqueue messages onto `recv_queue`.
    """

    def __init__(self, server: Any):
        self.server = server

        if os.name in ["posix"]:
            _fd, _path = tempfile.mkstemp(prefix="/tmp/ggb_")
            os.close(_fd)
            os.remove(_path)
            self.server.socket_path = _path
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest",
                    "raw": f"Reserved ingest socket_path {self.server.socket_path}",
                }
            )
        else:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            _, p = s.getsockname()
            self.server.ws_port = p
            s.close()
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest",
                    "raw": f"Reserved ingest ws_port {self.server.ws_port}",
                }
            )

    def serve_context(self):
        """Return an async context manager for starting the ingest websocket server.

        Usage:
            async with ingest_loop.serve_context() as ingest_server:
                ...
        """
        # Prepare path/port and return the appropriate websockets context manager
        if getattr(self.server, "socket_path", None):
            path = self.server.socket_path
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            return unix_serve(self.handler, path=path)
        else:
            port = getattr(self.server, "ws_port", None)
            if port is None:
                port = 0
            return serve(self.handler, "127.0.0.1", port)

    async def start(self):
        """Start the ingest WebSocket server and attach handle to the parent server.

        Returns the server handle (or None on failure).
        """
        if getattr(self.server, "socket_path", None):
            path = self.server.socket_path
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            ingest_server = await unix_serve(self.handler, path=path)
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest_ws",
                    "raw": f"Starting unix socket server at {path}",
                }
            )
        else:
            port = getattr(self.server, "ws_port", None)
            if port is None:
                port = 0
            ingest_server = await serve(self.handler, "127.0.0.1", port)
            self.server._push_raw_buffer(
                {
                    "ts": time.time(),
                    "dir": "ingest_ws",
                    "raw": f"Starting TCP socket server at 127.0.0.1:{port}",
                }
            )

        self.server.ingest_server = ingest_server
        return ingest_server

    async def handler(self, websocket):
        async for msg in websocket:
            self.server._push_raw_buffer({"ts": time.time(), "dir": "ingest_ws", "raw": msg})

            try:
                data = json.loads(msg) if isinstance(msg, str) else msg
                self.server._push_raw_buffer({"ts": time.time(), "dir": "ingest", "raw": f"Parsed ingest message: {data}",})
            except Exception:
                self.server._push_raw_buffer({"ts": time.time(), "dir": "ingest", "raw": f"Failed to parse ingest message: {msg}",})
                await self.server.recv_queue.put(msg)
                continue

            if isinstance(data, dict) and data.get("type") == "bulk_actions":
                payload = data.get("payload")
                if isinstance(payload, list):
                    for entry in payload:
                        if not isinstance(entry, dict):
                            continue
                        etype = entry.get("type")
                        epayload = entry.get("payload")
                        if etype == "object_update":
                            await self.server._handle_object_update(epayload)
                        else:
                            if isinstance(epayload, (dict, list)):
                                await self.server._handle_object_update(epayload)
                            else:
                                await self.server.recv_queue.put(entry)
                continue

            if isinstance(data, dict) and data.get("type") == "object_update":
                self.server._push_raw_buffer({"ts": time.time(), "dir": "ingest", "raw": f"Object update payload: {data.get('payload')}",})
                await self.server._handle_object_update(data.get("payload"))
                continue

            await self.server.recv_queue.put(data)


__all__ = ["IngestLoop"]
