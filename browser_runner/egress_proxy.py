"""Connection-time egress guard for the browser agent (Codex review on #334).

Chromium resolves hostnames itself, so checking a task's host before launch does not stop DNS rebinding, and page
sub-resources can name any host. Every browser connection therefore goes through this local CONNECT proxy: it resolves
the host itself, refuses the connection unless every address is public, and connects to the address it checked, so the
browser never gets a second, different answer. Plain-HTTP (non-CONNECT) requests are refused; tasks are https only.
"""
from __future__ import annotations

import ipaddress
import select
import socket
import socketserver
import threading
from typing import Callable

MAX_HEADER = 8192
IDLE_SECONDS = 30


def public_ip(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        client = self.request
        client.settimeout(IDLE_SECONDS)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < MAX_HEADER:
            chunk = client.recv(1024)
            if not chunk:
                return
            data += chunk
        line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace").split()
        if len(line) < 2 or line[0].upper() != "CONNECT":
            server.refused.append(("method", line[0] if line else ""))
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        host, _, port = line[1].rpartition(":")
        host = host.strip("[]").lower()
        if not host or not port.isdigit() or int(port) not in server.allowed_ports:
            server.refused.append(("port", line[1]))
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        try:
            infos = server.resolve(host, int(port), proto=socket.IPPROTO_TCP)
        except OSError:
            infos = []
        addresses = [info[4][0] for info in infos]
        if not addresses or not all(server.allow(a) for a in addresses):
            server.refused.append(("address", host))       # one private answer is enough to refuse
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        try:
            upstream = socket.create_connection((addresses[0], int(port)), timeout=15)
        except OSError:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        server.connected.append(host)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        with upstream:
            sockets = [client, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], IDLE_SECONDS)
                if not readable:
                    return
                for sock in readable:
                    chunk = sock.recv(65536)
                    if not chunk:
                        return
                    (upstream if sock is client else client).sendall(chunk)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class PublicOnlyProxy:
    """`with PublicOnlyProxy() as proxy:` → pass `proxy.url` to Chromium as its proxy server."""

    def __init__(self, *, resolve: Callable = socket.getaddrinfo, allow: Callable[[str], bool] = public_ip,
                 allowed_ports=(443,)):
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.resolve, self._server.allow = resolve, allow
        self._server.allowed_ports = frozenset(allowed_ports)
        self._server.refused, self._server.connected = [], []
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self._server.server_address[1]

    @property
    def refused(self) -> list:
        return self._server.refused

    @property
    def connected(self) -> list:
        return self._server.connected

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False
