#!/usr/bin/env python3
"""
Launch the proxy kernel as a standalone kernel process and open a
`jupyter console` connected to it.

This helper creates a temporary connection file, starts `tools/proxy_repl.py`
with `-f <connection_file>` so it behaves as a Jupyter kernel, then runs
`jupyter console --existing <connection_file>` to give a CLI to the kernel.
When the console exits, the kernel process is terminated.

Usage:
  python tools/launch_and_connect.py

Optional flags:
  --kernel-python /path/to/python  # which python to use for the kernel subprocess
"""
from __future__ import print_function
import argparse
import subprocess
import sys
import tempfile
import os
import time
import signal
import shutil
import logging
import json
try:
    from jupyter_client.kernelspec import KernelSpecManager
except Exception:
    KernelSpecManager = None


def find_jupyter_console():
    # Prefer `jupyter console` (part of jupyter_client) via `jupyter` CLI
    if shutil.which('jupyter'):
        return ['jupyter', 'console', '--existing']
    # fallback to jupyter-console entrypoint
    if shutil.which('jupyter-console'):
        return ['jupyter-console', '--existing']
    # fallback to python -m jupyter_console
    return [sys.executable, '-m', 'jupyter_console', '--existing']


def main():
    parser = argparse.ArgumentParser(description='Launch proxy kernel and open jupyter console connected to it')
    parser.add_argument('--kernel-python', help='Python executable to run kernel subprocess with')
    parser.add_argument('--kernel-cmd', help='Full kernel command to run for the kernel process (string). Use {connection_file} to place the connection file.')
    parser.add_argument('--install-kernelspec', action='store_true', help='Install a kernelspec that launches the proxy kernel')
    parser.add_argument('--kernelspec-name', default='ggblab-proxy', help='Name for the installed kernelspec')
    parser.add_argument('--kernelspec-display-name', default='ggblab Proxy Kernel', help='Display name for the kernelspec')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    proxy_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'proxy_repl.py'))
    if not os.path.exists(proxy_path):
        print('proxy_repl.py not found at', proxy_path, file=sys.stderr)
        sys.exit(2)

    def _install_kernelspec(proxy_path, name, display_name):
        if KernelSpecManager is None:
            print('jupyter_client not available; install jupyter_client to register kernelspec', file=sys.stderr)
            return 2
        # create a temporary kernelspec directory
        kdir = tempfile.mkdtemp(prefix='ggblab-kernelspec-')
        kjson = {
            'argv': [sys.executable, proxy_path, '-f', '{connection_file}'],
            'display_name': display_name,
            'language': 'python'
        }
        with open(os.path.join(kdir, 'kernel.json'), 'w', encoding='utf-8') as f:
            json.dump(kjson, f, indent=2)
        ksm = KernelSpecManager()
        try:
            ksm.install_kernel_spec(kdir, kernel_name=name, user=True, replace=True)
            print('Installed kernelspec', name)
            return 0
        except Exception as e:
            print('Failed to install kernelspec:', e, file=sys.stderr)
            return 3

    if args.install_kernelspec:
        rc = _install_kernelspec(proxy_path, args.kernelspec_name, args.kernelspec_display_name)
        sys.exit(rc)

    # create temporary connection file path (the file will be created by the kernel)
    tf = tempfile.NamedTemporaryFile(prefix='ggblab-connection-', suffix='.json', delete=False)
    conn_path = tf.name
    tf.close()

    if args.kernel_cmd:
        # Pass the kernel command string through to the proxy launcher
        kernel_cmd = [sys.executable, proxy_path, '--kernel-cmd', args.kernel_cmd, '-f', conn_path]
    elif args.kernel_python:
        # When proxy_repl is launched with -f it will itself spawn ipykernel subprocess using --kernel-python if provided.
        kernel_cmd = [sys.executable, proxy_path, '--kernel-python', args.kernel_python, '-f', conn_path]
    else:
        kernel_cmd = [sys.executable, proxy_path, '-f', conn_path]

    logging.info('Starting proxy kernel with command: %s', ' '.join(kernel_cmd))
    kp = subprocess.Popen(kernel_cmd)

    try:
        # Wait for connection file to be created by the kernel process
        for _ in range(50):
            if os.path.exists(conn_path) and os.path.getsize(conn_path) > 0:
                break
            if kp.poll() is not None:
                logging.error('Kernel process exited prematurely with code %s', kp.returncode)
                sys.exit(1)
            time.sleep(0.1)
        else:
            logging.error('Timed out waiting for kernel to create connection file')
            kp.terminate()
            sys.exit(1)

        jupyter_console_cmd = find_jupyter_console() + [conn_path]
        logging.info('Launching console: %s', ' '.join(jupyter_console_cmd))
        rc = subprocess.call(jupyter_console_cmd)
        logging.info('Console exited with code %s', rc)
    finally:
        # Attempt graceful shutdown
        try:
            if kp.poll() is None:
                kp.terminate()
                try:
                    kp.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    kp.kill()
        except Exception:
            pass
        # cleanup connection file
        try:
            if os.path.exists(conn_path):
                os.remove(conn_path)
        except Exception:
            pass


if __name__ == '__main__':
    main()
