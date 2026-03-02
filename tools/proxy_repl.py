#!/usr/bin/env python3
"""
Proxy REPL using BlockingKernelClient to mediate between a terminal and
an ipykernel subprocess. It forwards execute requests and relays iopub
output, shell replies, and stdin prompts (proxying input back to the kernel).

Usage:
  python tools/proxy_repl.py

This script starts a kernel subprocess via KernelManager, creates a
BlockingKernelClient, and then runs a simple terminal REPL. When the
kernel sends an `input_request` on the stdin channel, the proxy prompts
the terminal user and sends the reply back to the kernel.
"""
from __future__ import print_function
import sys
import os
import argparse
import time
from jupyter_client import KernelManager, BlockingKernelClient
import threading
import queue
import subprocess
import shlex
import logging
import json
try:
    from ipykernel.kernelbase import Kernel
    from ipykernel.kernelapp import IPKernelApp
except Exception:
    Kernel = None  # type: ignore
    IPKernelApp = None  # type: ignore


def start_kernel(kernel_cmd=None, env=None, timeout=10):
    km = KernelManager()
    if kernel_cmd:
        logging.debug('Setting kernel_cmd: %s', kernel_cmd)
        km.kernel_cmd = kernel_cmd
    logging.debug('Starting kernel; PYTHONPATH=%s', env.get('PYTHONPATH') if env else None)
    km.start_kernel(env=env)
    kc = km.client()
    kc.start_channels()
    try:
        kc.wait_for_ready(timeout=timeout)
    except Exception:
        print('Warning: kernel did not report ready in time', file=sys.stderr)
    return km, kc


def handle_iopub_msg(msg):
    mtype = msg.get('header', {}).get('msg_type')
    logging.debug('iopub msg: %s', mtype)
    content = msg.get('content', {})
    if mtype == 'stream':
        sys.stdout.write(content.get('text', ''))
        sys.stdout.flush()
    elif mtype in ('execute_result', 'display_data'):
        data = content.get('data', {})
        text = data.get('text/plain')
        if text is not None:
            print(text)
    elif mtype == 'error':
        for line in content.get('traceback', []):
            print(line, file=sys.stderr)
    elif mtype == 'status':
        # execution_state may be 'busy' or 'idle'
        pass


def handle_shell_msg(msg):
    # shell messages include execute_reply and others
    mtype = msg.get('header', {}).get('msg_type')
    content = msg.get('content', {})
    logging.debug('shell msg: %s', mtype)
    if mtype == 'execute_reply':
        if 'user_expressions' in content:
            # could print execution count
            pass


class JuliaProxyKernel(Kernel if Kernel is not None else object):
    """Kernel that forwards execute requests to a persistent Julia REPL.

    It starts a Julia subprocess and relays its stdout/stderr back to the
    front-end as `stream` iopub messages. Each execute wraps the user
    code to emit a unique end-marker so the kernel can determine when the
    evaluation finished.
    """
    implementation = "julia-proxy"
    implementation_version = "0.1"
    language = "julia"
    language_info = {"name": "julia", "mimetype": "text/x-julia", "file_extension": ".jl"}
    banner = "Julia proxy kernel (persistent Julia REPL)"

    def __init__(self, **kwargs):
        if Kernel is None:
            raise RuntimeError('ipykernel not available in this environment')
        super().__init__(**kwargs)
        self._start_julia_process()

    def _start_julia_process(self):
        # Start a persistent Julia REPL subprocess. Use -i for interactive
        # mode and --startup-file=no to avoid user profile evals.
        cmd = ['/Users/manabu/.juliaup/bin/julia', '--startup-file=no', '--color=no', '-i']
        self._julia_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self._out_queue = queue.Queue()
        # Reader threads
        def _read_out(pipe, kind):
            try:
                for line in iter(pipe.readline, ''):
                    self._out_queue.put((kind, line))
            except Exception:
                pass
        self._out_thread = threading.Thread(target=_read_out, args=(self._julia_proc.stdout, 'stdout'), daemon=True)
        self._err_thread = threading.Thread(target=_read_out, args=(self._julia_proc.stderr, 'stderr'), daemon=True)
        self._out_thread.start()
        self._err_thread.start()

    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        if not code or not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count, 'payload': [], 'user_expressions': {}}

        # Unique marker to detect end of execution
        marker = f'__GGB_END_{int(time.time() * 1000)}__'

        # Wrap code so that Julia prints the result (if any) and the marker.
        # Use triple-quoted string to embed arbitrary user code safely.
        wrapper = (
            'begin\n'
            '  try\n'
            f'    _ggblab_val = eval(Meta.parse("""{code}"""))\n'
            '    if _ggblab_val !== nothing\n'
            '      try\n'
            '        println(_ggblab_val)\n'
            '      catch e\n'
            '        println(stderr, e)\n'
            '      end\n'
            '    end\n'
            '  catch e\n'
            '    println(stderr, e)\n'
            '  end\n'
            f'  println("{marker}")\n'
            'end\n'
        )

        # Send wrapper to Julia stdin
        try:
            if self._julia_proc.poll() is not None:
                # Julia exited unexpectedly
                return {'status': 'error', 'ename': 'JuliaExit', 'evalue': 'Julia process terminated', 'traceback': []}
            self._julia_proc.stdin.write(wrapper)
            self._julia_proc.stdin.flush()
        except Exception as e:
            return {'status': 'error', 'ename': type(e).__name__, 'evalue': str(e), 'traceback': []}

        # Collect output until marker seen
        collected = []
        found = False
        # Give a generous timeout per execute (adjustable)
        timeout_seconds = 30
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                kind, text = self._out_queue.get(timeout=0.1)
            except queue.Empty:
                # poll Julia process
                if self._julia_proc.poll() is not None:
                    # process died
                    return {'status': 'error', 'ename': 'JuliaExit', 'evalue': 'Julia process terminated', 'traceback': []}
                continue
            if text is None:
                continue
            # forward to front-end as stream
            stream_name = 'stdout' if kind == 'stdout' else 'stderr'
            try:
                self.send_response(self.iopub_socket, 'stream', {'name': stream_name, 'text': text})
            except Exception:
                pass
            collected.append((stream_name, text))
            if marker in text:
                found = True
                break

        if not found:
            return {'status': 'error', 'ename': 'TimeoutError', 'evalue': f'No marker {marker} from Julia within timeout', 'traceback': []}

        # Success
        return {'status': 'ok', 'execution_count': self.execution_count, 'payload': [], 'user_expressions': {}}

    def do_shutdown(self, restart=False):
        try:
            if hasattr(self, '_julia_proc') and self._julia_proc and self._julia_proc.poll() is None:
                try:
                    self._julia_proc.terminate()
                except Exception:
                    pass
        except Exception:
            pass
        return {'status': 'ok'}


def handle_stdin_msg(kc, msg):
    # msg is an input_request
    content = msg.get('content', {})
    prompt = content.get('prompt', '')
    password = content.get('password', False)
    logging.debug('stdin request prompt=%r password=%s', prompt, password)
    try:
        if password:
            # fallback to getpass if password requested
            import getpass
            val = getpass.getpass(prompt)
        else:
            val = input(prompt)
    except EOFError:
        val = ''
    # send reply back to kernel
    try:
        kc.input(val)
    except Exception:
        # older/newer client variations may require using kc.stdin_channel
        try:
            kc.stdin_channel.send({'header': {}, 'parent_header': msg.get('parent_header'), 'content': {'value': val}})
        except Exception:
            pass


def execute_and_collect(kc, code, timeout=0.1):
    if not code.strip():
        return
    msg_id = kc.execute(code, allow_stdin=True)
    while True:
        handled = False
        # try iopub
        try:
            msg = kc.get_iopub_msg(timeout=timeout)
        except Exception:
            msg = None
        if msg:
            parent = msg.get('parent_header', {})
            if parent.get('msg_id') == msg_id:
                handle_iopub_msg(msg)
            handled = True
            # stop on status idle
            if msg.get('header', {}).get('msg_type') == 'status' and msg.get('content', {}).get('execution_state') == 'idle':
                break

        # try shell messages
        try:
            sh = kc.get_shell_msg(timeout=0)
        except Exception:
            sh = None
        if sh:
            parent = sh.get('parent_header', {})
            if parent.get('msg_id') == msg_id:
                handle_shell_msg(sh)
            handled = True

        # try stdin messages (input_request)
        try:
            stdin_msg = kc.get_stdin_msg(timeout=0)
        except Exception:
            stdin_msg = None
        if stdin_msg:
            handle_stdin_msg(kc, stdin_msg)
            handled = True

        if not handled:
            # no messages this loop; sleep briefly to avoid busy-spin
            time.sleep(timeout)


def repl_loop(kc):
    prompt = 'ggblab-proxy> '
    try:
        while True:
            try:
                code = input(prompt)
            except EOFError:
                print('\nExiting...')
                break
            if not code:
                continue
            if code.strip() in ('exit', 'quit'):
                break
            # multiline support: trailing backslash
            if code.endswith('\\'):
                lines = [code[:-1]]
                while True:
                    more = input('... ')
                    if more.endswith('\\'):
                        lines.append(more[:-1])
                        continue
                    lines.append(more)
                    break
                code = '\n'.join(lines)
            execute_and_collect(kc, code)
    except KeyboardInterrupt:
        print('\nKeyboardInterrupt — stopping REPL')


def main():
    parser = argparse.ArgumentParser(description='Proxy REPL using BlockingKernelClient')
    parser.add_argument('--kernel-python', help='Python executable to run kernel subprocess with')
    parser.add_argument('--kernel-cmd', help='Full kernel command to run (string). Use {connection_file} to place the connection file.')
    parser.add_argument('-f', '--connection-file', dest='connection_file', help='Jupyter connection file (when launched as a kernel)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    env = os.environ.copy()
    old_pp = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = repo_root + (os.pathsep + old_pp if old_pp else '')

    logging.debug('Repo root=%s', repo_root)
    logging.debug('Effective PYTHONPATH=%s', env['PYTHONPATH'])

    km, kc = None, None
    try:
        if args.connection_file:
            # Launched by Jupyter as a kernel: run an in-process IPKernelApp
            # whose Kernel class proxies to a persistent Julia REPL.
            if IPKernelApp is None or Kernel is None:
                logging.error('ipykernel is required to run in kernel mode')
                raise RuntimeError('ipykernel not available')
            # Ensure the kernel class used by the app is our JuliaProxyKernel
            logging.debug('Starting IPKernelApp with JuliaProxyKernel')
            app = IPKernelApp.instance()
            app.kernel_class = JuliaProxyKernel
            # Initialize with the connection file path so it binds correctly
            app.initialize(argv=[f'--f', args.connection_file])
            try:
                app.start()
            except KeyboardInterrupt:
                pass
        else:
            # Interactive proxy REPL mode (standalone)
            kernel_cmd = None
            if args.kernel_cmd:
                parts = shlex.split(args.kernel_cmd)
                if any('{connection_file}' in p for p in parts):
                    kernel_cmd = parts
                else:
                    kernel_cmd = parts + ['{connection_file}']
            elif args.kernel_python:
                kernel_cmd = [args.kernel_python, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
            km, kc = start_kernel(kernel_cmd=kernel_cmd, env=env)
            logging.info('Proxy kernel started; you can `import ggblab` from the kernel.')
            repl_loop(kc)
    finally:
        if kc:
            try:
                kc.stop_channels()
            except Exception:
                pass
        if km:
            try:
                km.shutdown_kernel(now=True)
            except Exception:
                pass


if __name__ == '__main__':
    main()
