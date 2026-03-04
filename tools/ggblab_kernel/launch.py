#!/usr/bin/env python3
"""
Simplified kernel launcher for ggblab development.

This launcher ensures the repository root is on PYTHONPATH so the
developer checkout can be imported without pip-installing, then starts
an IPython kernel bound to the connection file provided by Jupyter.

It is intentionally small and predictable. Use the accompanying
generate_kernelspec.py to write a kernelspec `kernel.json` that points
to this launcher.
"""
from __future__ import annotations
import os
import sys
import argparse

# Make repository root importable (assumes this file is in tools/ggblab_kernel/)
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

try:
    import ggblab  # noqa: F401
except Exception as e:  # pragma: no cover - best-effort import for dev
    print('Warning: failed to import ggblab at startup:', e, file=sys.stderr)

try:
    # Prefer launching in-process when available
    from ipykernel.kernelapp import IPKernelApp
except Exception:
    IPKernelApp = None

    import threading
    import socketserver
    import http.server
    import json
    import tempfile
    import atexit


def main():
    # Sanitize argv to strip Jupyter application-scoped options that some
    # frontends pass (e.g. --_App.connection_file). This prevents
    # argparse in this launcher from treating them as unrecognized.
    try:
        _orig_argv = list(sys.argv)
        _parser = argparse.ArgumentParser(add_help=False)
        _parser.add_argument('-f', '--connection-file', dest='connection_file')
        # _parser.add_argument('--_App.connection_file', dest='connection_file')
        _known, _unknown = _parser.parse_known_args(_orig_argv[1:])
        _sanitized = [sys.argv[0]]
        if getattr(_known, 'connection_file', None):
            _sanitized.extend(['-f', getattr(_known, 'connection_file')])
        # If no connection file found but a bare json arg exists, use that
        if len(_sanitized) == 1:
            for a in _orig_argv[1:]:
                if a.endswith('.json') and not a.startswith('--'):
                    _sanitized.extend(['-f', a])
                    break
        if _sanitized != _orig_argv:
            sys.argv = _sanitized
    except Exception:
        # If anything goes wrong, leave sys.argv alone and continue
        pass

    parser = argparse.ArgumentParser(description='Simple ggblab kernel launcher')
    parser.add_argument('-f', '--connection-file', dest='connection_file', help='Connection file path passed by Jupyter')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    if not args.connection_file:
        print('Expected -f <connection_file> argument from Jupyter', file=sys.stderr)
        sys.exit(2)

    if args.debug:
        print('[DEBUG] Repo root:', repo_root, file=sys.stderr)

    # Make sure child kernel process will import the repo when spawned
    os.environ['PYTHONPATH'] = repo_root + (os.pathsep + os.environ.get('PYTHONPATH', '') if os.environ.get('PYTHONPATH') else '')

    argv = ['-f', args.connection_file]
    # If ipykernel is available, start in-process which matches Jupyter's expectation
    if IPKernelApp is not None:
        ggblab_flag = os.environ.get('GGBLAB_ENABLE', '').lower() in ('1', 'true')
        
        if ggblab_flag:
            print(f"GGBLAB_ENABLE={ggblab_flag} (from environment variable)")
            # Subclass IPKernelApp to inject InteractiveShellApp.exec_lines
            class GGBlabApp(IPKernelApp):
                def initialize(self, argv=None):
                    # super().initialize(argv)
                    print('Injecting ggblab init into kernel config')
                    try:
                        
                        from traitlets.config import Config
                        snippet = (
                            "from ggblab_core.applet import AppletInjector\n"
                            "from ggblab_core.applet import function_sync, command_sync\n"
                            "ggb = AppletInjector()\n"
                            "ggb.open(wait_for_open=False)"
                        )
                        c = Config()
                        existing = []
                        try:
                            existing = list(getattr(self.config.InteractiveShellApp, 'exec_lines', []) or [])
                        except Exception:
                            existing = []
                        existing.append(snippet)
                        print('Injecting ggblab init into InteractiveShellApp.exec_lines:', existing)
                        c.InteractiveShellApp.exec_lines = existing
                        self.update_config(c)
                    except Exception:
                        # Fail silently; kernel can still start without ggblab init
                        print('Failed to inject ggblab init into kernel config:', file=sys.stderr)
                        pass
                    # Start a tiny control HTTP server to accept requests from
                    # other kernels (Python/Julia) that want to call
                    # `function_sync`/`command_sync` on this kernel.
                    try:
                        class _Handler(http.server.BaseHTTPRequestHandler):
                            def do_POST(self):
                                try:
                                    length = int(self.headers.get('Content-Length', '0'))
                                    body = self.rfile.read(length) if length else b''
                                    payload = json.loads(body.decode('utf8') if body else '{}')
                                except Exception as e:
                                    self.send_response(400)
                                    self.end_headers()
                                    self.wfile.write(b'')
                                    return

                                resp = {"ok": False}
                                try:
                                    # Allowed request types: function_sync, command_sync
                                    rtype = payload.get('type')
                                    if rtype == 'function_sync':
                                        from ggblab_core.applet import function_sync
                                        name = payload.get('name')
                                        args = payload.get('args', None)
                                        timeout = payload.get('timeout', None)
                                        try:
                                            result = function_sync(name, args=args, timeout=timeout)
                                            resp = {"ok": True, "result": result}
                                        except Exception as e:
                                            resp = {"ok": False, "error": str(e)}
                                    elif rtype == 'command_sync':
                                        from ggblab_core.applet import command_sync
                                        command = payload.get('command', '')
                                        timeout = payload.get('timeout', None)
                                        try:
                                            result = command_sync(command, timeout=timeout)
                                            resp = {"ok": True, "result": result}
                                        except Exception as e:
                                            resp = {"ok": False, "error": str(e)}
                                    else:
                                        resp = {"ok": False, "error": 'unknown request type'}
                                except Exception as e:
                                    resp = {"ok": False, "error": str(e)}

                                body_out = json.dumps(resp).encode('utf8')
                                self.send_response(200 if resp.get('ok') else 500)
                                self.send_header('Content-Type', 'application/json')
                                self.send_header('Content-Length', str(len(body_out)))
                                self.end_headers()
                                try:
                                    self.wfile.write(body_out)
                                except Exception:
                                    pass

                            def log_message(self, format, *args):
                                # silence default logging
                                return

                        # Bind to localhost on an ephemeral port
                        server = socketserver.TCPServer(('127.0.0.1', 0), _Handler)
                        server.allow_reuse_address = True

                        def _serve():
                            try:
                                server.serve_forever()
                            except Exception:
                                pass

                        t = threading.Thread(target=_serve, daemon=True)
                        t.start()

                        # Write a small port file so external kernels can discover it
                        try:
                            info = {'port': server.server_address[1], 'pid': os.getpid()}
                            portfile_dir = os.path.join(repo_root, '.ggblab')
                            os.makedirs(portfile_dir, exist_ok=True)
                            portfile = os.path.join(portfile_dir, 'control_port.json')
                            with open(portfile, 'w') as f:
                                json.dump(info, f)
                        except Exception:
                            pass

                        # ensure cleanup on exit
                        def _cleanup():
                            try:
                                server.shutdown()
                            except Exception:
                                pass
                            try:
                                server.server_close()
                            except Exception:
                                pass
                            try:
                                if os.path.exists(portfile):
                                    os.remove(portfile)
                            except Exception:
                                pass

                        atexit.register(_cleanup)
                    except Exception:
                        print('Failed to start ggblab control server', file=sys.stderr)
                    # Finally initialize the kernel app normally
                    super().initialize(argv)

            try:
                GGBlabApp.launch_instance(argv=argv)
            except SystemExit:
                return
            except Exception as e:
                print('Failed to launch in-process ipykernel (with ggblab init):', e, file=sys.stderr)
                sys.exit(1)
        else:
            try:
                IPKernelApp.launch_instance(argv=argv)
            except SystemExit:
                return
            except Exception as e:
                print('Failed to launch in-process ipykernel:', e, file=sys.stderr)
                sys.exit(1)

    # Fallback: spawn a subprocess using the same python interpreter
    kernel_cmd = [sys.executable, '-m', 'ipykernel_launcher'] + argv
    os.execvpe(kernel_cmd[0], kernel_cmd, os.environ)


if __name__ == '__main__':
    main()
