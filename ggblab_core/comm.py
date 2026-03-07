"""Synchronous Comm wrapper using jupyter_client.BlockingKernelClient.

This provides a lightweight `CommSync` class that opens a comm target
on a kernel (the kernel must have a corresponding target handler
registered), sends messages and waits synchronously for `comm_msg`
replies on the iopub channel. The implementation intentionally avoids
any Out-Of-Band (OOB) event loop and uses `BlockingKernelClient`'s
blocking receive calls.

Notes
-----
- The kernel must register a comm target with `target_name` (see
  `example.py`) and reply to messages by calling `comm.send(...)`.
- This class does minimal message filtering: it reads `iopub` messages
  and returns the first `comm_msg` whose `content.comm_id` matches
  the opened comm id.
"""

import logging
import time
import uuid
from typing import Any, Optional

try:
    from jupyter_client import BlockingKernelClient
except Exception:  # pragma: no cover - import-time safety
    BlockingKernelClient = None

_log = logging.getLogger(__name__)


class CommSync:
    """Minimal synchronous Comm using a BlockingKernelClient.

    Parameters
    - kernel_client: an instance of `jupyter_client.BlockingKernelClient`
      already connected to the target kernel (channels started).
    - target_name: the comm target name registered on the kernel.
    - timeout: seconds to wait for replies.
    """

    def __init__(
        self,
        kernel_client: BlockingKernelClient,
        target_name: str,
        timeout: float = 5.0,
    ):
        if BlockingKernelClient is None:
            raise RuntimeError("jupyter_client.BlockingKernelClient is required")
        self.kc = kernel_client
        self.target_name = target_name
        self.timeout = float(timeout)
        self.comm_id: Optional[str] = None
        self._inproc_handler = None

    def _ensure_channels(self) -> None:
        try:
            # start_channels is idempotent if already started
            self.kc.start_channels()
        except Exception as e:
            _log.debug("start_channels() raised: %s", e)

    def open(self, data: Optional[dict] = None) -> str:
        """Open a comm to the kernel target and return the comm id.

        The method generates a UUID for `comm_id` and sends a `comm_open`
        message to the kernel target. The kernel should handle the open
        on its side (register the comm) before messages are exchanged.
        """
        self._ensure_channels()
        self.comm_id = str(uuid.uuid4())
        # Send comm_open with an assigned comm_id so kernel knows the id
        try:
            # BlockingKernelClient exposes helper methods for comms
            self.kc.comm_open(
                target_name=self.target_name, data=data or {}, comm_id=self.comm_id
            )
        except Exception:
            raise
        return self.comm_id

    def send(self, data: Any) -> Any:
        """Send `data` and wait synchronously for a comm reply.

        Returns the `data` field from the first matching `comm_msg`.
        Raises `TimeoutError` when no reply is received within `timeout`.
        """
        if not self.comm_id:
            raise RuntimeError("Comm not opened; call open() first")

        # send the message via real kernel client
        self.kc.comm_msg(data=data, comm_id=self.comm_id)

        # wait for a reply on iopub
        deadline = time.time() + self.timeout
        while True:
            remaining = max(0.0, deadline - time.time())
            if remaining == 0:
                break
            try:
                msg = self.kc.get_iopub_msg(timeout=remaining)
            except Exception:
                # any get_iopub_msg error -> timeout/connection issue
                break
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("header", {}).get("msg_type")
            if mtype != "comm_msg":
                # ignore unrelated iopub messages
                continue
            content = msg.get("content", {})
            # content may include 'comm_id' or nested 'comm' key depending on version
            received_comm_id = content.get("comm_id") or content.get("comm", {}).get(
                "comm_id"
            )
            if received_comm_id == self.comm_id:
                return content.get("data")
        raise TimeoutError(
            f"No comm reply for comm_id={self.comm_id} within {self.timeout}s"
        )

    def close(self) -> None:
        """Close the comm on the kernel side (attempt, ignore failures)."""
        if not self.comm_id:
            return
        try:
            self.kc.comm_close(comm_id=self.comm_id)
        except Exception as e:
            _log.debug("comm_close failed: %s", e)
        finally:
            self.comm_id = None
