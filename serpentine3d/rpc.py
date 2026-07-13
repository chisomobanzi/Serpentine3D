"""Localhost JSON-RPC bridge into the running GUI.

The MCP server (a separate stdio process) connects here. Protocol:
newline-delimited JSON  {"method": str, "params": {...}, "id": n}
->  {"result": ..., "id": n}  or  {"error": str, "id": n}

Handlers execute on the Qt main thread via a blocking queued signal.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import traceback

from PySide6.QtCore import QObject, Qt, Signal

from .api import ApiError, SerpApi

DEFAULT_PORT = 5757
PORT_FILE = os.path.expanduser("~/.serpentine3d/rpc.port")


class RpcServer(QObject):
    _invoke = Signal(object)

    def __init__(self, window):
        super().__init__()
        self.api = SerpApi(window)
        self.port = None
        self._sock = None
        self._invoke.connect(self._run_job,
                             Qt.ConnectionType.BlockingQueuedConnection)

    # -- main-thread execution --

    def _run_job(self, job):
        try:
            job["result"] = job["fn"]()
        except ApiError as exc:
            job["error"] = str(exc)
        except Exception as exc:                              # noqa: BLE001
            job["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            job["done"].set()

    def call(self, method: str, params: dict):
        fn = getattr(self.api, method, None)
        if fn is None or method.startswith("_"):
            raise ApiError(f"Unknown method '{method}'")
        job = {"fn": lambda: fn(**(params or {})),
               "done": threading.Event()}
        self._invoke.emit(job)
        job["done"].wait(timeout=120)
        if "error" in job:
            raise ApiError(job["error"])
        return job.get("result")

    # -- socket plumbing (worker threads) --

    def start(self):
        port = int(os.environ.get("SERP3D_RPC_PORT", DEFAULT_PORT))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bound = False
        for candidate in range(port, port + 20):
            try:
                self._sock.bind(("127.0.0.1", candidate))
                self.port = candidate
                bound = True
                break
            except OSError:
                continue
        if not bound:
            print("serpentine3d: no free RPC port; MCP bridge disabled")
            return
        self._sock.listen(4)
        os.makedirs(os.path.dirname(PORT_FILE), exist_ok=True)
        with open(PORT_FILE, "w") as f:
            f.write(str(self.port))
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,),
                             daemon=True).start()

    def _serve(self, conn: socket.socket):
        buf = b""
        with conn:
            while True:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    response = self._handle_line(line)
                    try:
                        conn.sendall(response.encode() + b"\n")
                    except OSError:
                        return

    def _handle_line(self, line: bytes) -> str:
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            result = self.call(req.get("method", ""), req.get("params"))
            return json.dumps({"result": result, "id": req_id})
        except ApiError as exc:
            return json.dumps({"error": str(exc), "id": req_id})
        except Exception as exc:                              # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}",
                               "id": req_id})
