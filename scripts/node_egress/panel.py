#!/usr/bin/python3
"""Socket-activated panel extension. Authenticate against the live panel per request."""

import http.client
import ipaddress
import json
import os
import re
import socket
import socketserver
import subprocess
from http.server import BaseHTTPRequestHandler
from pathlib import Path


class PanelConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(4)
        self.sock.connect("/run/marzban/marzban.sock")


def authorize(token):
    if not token.startswith("Bearer ") or len(token) > 8192:
        return 401
    conn = PanelConnection("localhost")
    try:
        conn.request("GET", "/api/admin", headers={"Authorization": token})
        r = conn.getresponse()
        if r.status != 200:
            return r.status
        return 200 if json.load(r).get("is_sudo") is True else 403
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve(self):
        match = re.fullmatch(r"/api/node-egress/([1-9][0-9]*)", self.path)
        if not match:
            return self.reply(404, {})
        result = authorize(self.headers.get("Authorization", ""))
        if result != 200:
            return self.reply(result, {})
        nodes = json.loads(Path("/etc/marzban-egress-panel/nodes.json").read_text())
        target = nodes.get(match[1])
        if not target:
            return self.reply(
                200 if self.command == "GET" else 409, {"available": False}
            )
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", target):
            raise ValueError()
        args = ["status"]
        if self.command == "POST":
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1024:
                return self.reply(400, {})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            action = data.get("action")
            if action == "reset":
                uid = str(data.get("id", ""))
                if not re.fullmatch(r"[1-9][0-9]{0,18}", uid):
                    raise ValueError()
                args = [
                    "reset",
                    uid,
                    str(ipaddress.IPv6Address(data["expected_address"])),
                ]
            elif action in ("on", "off", "refresh"):
                args = [action]
            else:
                raise ValueError()
        r = subprocess.run(
            [
                "/usr/bin/ssh",
                "-F",
                "/etc/marzban-egress-panel/ssh_config",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-T",
                target,
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=110,
            check=False,
        )
        if r.returncode:
            return self.reply(
                409 if "Allocation changed" in r.stderr else 503,
                {"detail": "Node operation failed; reload current status."},
            )
        return self.reply(200, dict(json.loads(r.stdout), available=True))

    def do_GET(self):
        try:
            self.serve()
        except (TypeError, ValueError, KeyError):
            self.reply(400, {"detail": "Invalid request"})
        except (OSError, subprocess.SubprocessError, http.client.HTTPException):
            self.reply(503, {"detail": "Node controller unavailable"})

    do_POST = do_GET


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    if (
        os.environ.get("LISTEN_PID") != str(os.getpid())
        or os.environ.get("LISTEN_FDS") != "1"
    ):
        raise SystemExit("Expected one systemd activation socket")
    with Server("", Handler, bind_and_activate=False) as server:
        server.socket.close()
        server.socket = socket.socket(fileno=3)
        server.serve_forever()
