"""Simple OOB client that connects to a ggblab TCP bridge and prints
incoming messages to stdout.

This client uses a plain TCP line protocol compatible with
`comm_bridge.client.request` and the bridge server. It connects to
`host:port`, reads newline-terminated JSON messages and prints them.

Usage:
  python comm_bridge/oob_client.py --host 127.0.0.1 --port 8765
Or set environment variable `GGB_WS_PORT` to choose the port.
"""

import argparse
import json
import os
import socket
import sys
import time


def _read_loop(sock: socket.socket):
    f = sock.makefile("rwb")
    try:
        local_seq = 0
        local_objs = {}
        while True:
            line = f.readline()
            if not line:
                # connection closed
                return
            try:
                text = line.decode("utf-8", errors="replace").strip()
            except Exception:
                text = line.decode("utf-8", errors="replace").strip()
            try:
                obj = json.loads(text)
            except Exception:
                obj = text

            # Handle shared_objects snapshot/update semantics when available
            try:
                if isinstance(obj, dict) and obj.get("type") == "shared_objects_snapshot":
                    local_seq = obj.get("seq", 0)
                    local_objs = obj.get("payload", {}) or {}
                    print(json.dumps({"type": "shared_objects_snapshot", "seq": local_seq, "payload": local_objs}, ensure_ascii=False))
                    continue

                if isinstance(obj, dict) and obj.get("type") == "shared_objects_update":
                    seq = obj.get("seq", 0)
                    payload = obj.get("payload", {}) or {}
                    if seq and seq > local_seq:
                        local_objs.update(payload)
                        local_seq = seq
                        print(json.dumps({"type": "shared_objects_update", "seq": seq, "payload": payload}, ensure_ascii=False))
                    else:
                        # ignore old/duplicate updates
                        continue
            except Exception:
                pass

            print(json.dumps(obj, ensure_ascii=False))
    finally:
        try:
            f.close()
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser(description="ggblab OOB TCP client")
    p.add_argument("--host", default="127.0.0.1", help="Host to connect to (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="TCP port to connect to (default 8765)")
    args = p.parse_args()

    port = args.port or 8765
    host = args.host

    while True:
        try:
            s = socket.create_connection((host, port), timeout=10.0)
            try:
                # Request a snapshot on connect to catch up before live updates
                try:
                    req = json.dumps({"op": "get_shared_snapshot"}) + "\n"
                    s.sendall(req.encode("utf-8"))
                except Exception:
                    pass
                _read_loop(s)
            finally:
                try:
                    s.close()
                except Exception:
                    pass
            # exit after clean close
            return
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"Connection failed: {e}; retrying in 0.5s", file=sys.stderr)
            try:
                time.sleep(0.5)
            except Exception:
                return


if __name__ == "__main__":
    main()
