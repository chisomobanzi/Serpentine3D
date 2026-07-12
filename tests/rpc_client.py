"""Tiny RPC client for driving a running Serpentine (used by tests + MCP)."""

import json
import os
import socket


class SerpClient:
    def __init__(self, port: int | None = None, timeout: float = 60.0):
        if port is None:
            port_file = os.path.expanduser("~/.serpentine/rpc.port")
            port = int(open(port_file).read().strip())
        self.sock = socket.create_connection(("127.0.0.1", port),
                                             timeout=timeout)
        self._buf = b""
        self._id = 0

    def call(self, method: str, **params):
        self._id += 1
        msg = json.dumps({"method": method, "params": params,
                          "id": self._id})
        self.sock.sendall(msg.encode() + b"\n")
        while b"\n" not in self._buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("server closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]


if __name__ == "__main__":
    import sys
    client = SerpClient()
    method = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(client.call(method, **params), indent=2))
