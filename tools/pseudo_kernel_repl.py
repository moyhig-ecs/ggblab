#!/usr/bin/env python3
"""
Pseudo Jupyter-kernel REPL using jupyter_client.

Run this script in a Jupyter terminal to start a kernel process and interact
with it from a simple terminal REPL. You can then `import ggblab` and call
into the package to verify it works from the kernel context.

Example:
  python tools/pseudo_kernel_repl.py

Controls:
  - Type Python code and press Enter to execute.
  - Use an empty line to skip.
  - Type `exit` or press Ctrl-D to quit.
"""
from __future__ import print_function
import sys
import argparse
import time
from jupyter_client import KernelManager


def start_kernel(kernel_python=None, timeout=10):
    km = KernelManager()
    if kernel_python:
        km.kernel_cmd = [kernel_python, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    km.start_kernel()
    kc = km.client()
    kc.start_channels()
    try:
        kc.wait_for_ready(timeout=timeout)
    except Exception:
        print('Kernel did not become ready within timeout', file=sys.stderr)
    return km, kc


def execute_and_print(kc, code, timeout=1.0):
    if not code.strip():
        return
    msg_id = kc.execute(code)
    # Read iopub messages related to this execution until we see status: idle
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=timeout)
        except Exception:
            # timeout waiting for messages; continue to try until idle
            continue
        # filter messages by parent header msg_id
        parent = msg.get('parent_header', {})
        if parent.get('msg_id') != msg_id:
            continue
        mtype = msg.get('header', {}).get('msg_type')
        content = msg.get('content', {})
        if mtype == 'stream':
            sys.stdout.write(content.get('text', ''))
            sys.stdout.flush()
        elif mtype in ('execute_result', 'display_data'):
            data = content.get('data', {})
            if 'text/plain' in data:
                print(data['text/plain'])
        elif mtype == 'error':
            for line in content.get('traceback', []):
                print(line, file=sys.stderr)
        elif mtype == 'status' and content.get('execution_state') == 'idle':
            break


def repl(kc):
    prompt = 'ggblab-kernel> '
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
            # allow multiline mode when trailing backslash
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
            execute_and_print(kc, code)
    except KeyboardInterrupt:
        print('\nKeyboardInterrupt — stopping REPL')


def main():
    parser = argparse.ArgumentParser(description='Run a simple REPL that talks to a Jupyter kernel via jupyter_client')
    parser.add_argument('--kernel-python', help='Python executable to launch the kernel with (e.g. /path/to/python)')
    args = parser.parse_args()

    km, kc = None, None
    try:
        km, kc = start_kernel(kernel_python=args.kernel_python)
        print('Kernel started. You can now `import ggblab` and exercise it.')
        print('Type `exit` or Ctrl-D to quit.')
        repl(kc)
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
