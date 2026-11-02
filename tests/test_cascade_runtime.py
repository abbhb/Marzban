"""Optional real-core check: local SOCKS entry -> Shadowsocks landing -> HTTP.

Run with MIHOMO_TEST_BINARY=/path/to/mihomo. The proxy path stays on loopback.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import select
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest

import yaml

from app.subscription.cascade import entry_key
from app.subscription.clash import ClashMetaConfiguration


def read_exact(connection, length):
    result = b""
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise EOFError()
        result += chunk
    return result


class Entry(socketserver.BaseRequestHandler):
    def handle(self):
        connection = self.request
        connection.settimeout(5)
        try:
            version, count = read_exact(connection, 2)
            read_exact(connection, count)
            connection.sendall(b"\x05\x00")
            version, command, _, family = read_exact(connection, 4)
            if version != 5 or command != 1:
                return
            if family == 1:
                address = socket.inet_ntoa(read_exact(connection, 4))
            elif family == 3:
                address = read_exact(connection, read_exact(connection, 1)[0]).decode()
            else:
                return
            port = int.from_bytes(read_exact(connection, 2), "big")
            # The entry must never connect anywhere except the test landing.
            if (address, port) != self.server.landing:
                return
            self.server.hops.append((address, port))
            with socket.create_connection((address, port), timeout=5) as upstream:
                connection.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                while True:
                    readable, _, _ = select.select([connection, upstream], [], [], 5)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is connection else connection).sendall(data)
        except (OSError, EOFError):
            return


class Target(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"two-hop-route-confirmed"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


@unittest.skipUnless(os.environ.get("MIHOMO_TEST_BINARY"), "Set MIHOMO_TEST_BINARY to test the real core")
class CascadeRuntimeTests(unittest.TestCase):
    def test_real_tcp_chain_and_entry_failure_without_direct_fallback(self):
        binary = os.environ["MIHOMO_TEST_BINARY"]
        target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        entry = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Entry)
        entry.daemon_threads = True
        entry.hops = []
        entry.landing = ("127.0.0.1", free_port())
        for server in (target, entry):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        local_port = free_port()
        password = "test-landing-only"
        with tempfile.TemporaryDirectory(prefix="cascade-real-core-") as directory:
            def start_core(name, document):
                root = Path(directory) / name
                root.mkdir()
                config = root / "config.yaml"
                config.write_text(yaml.safe_dump(document, allow_unicode=True))
                check = subprocess.run([binary, "-t", "-d", str(root), "-f", str(config)], capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                process = subprocess.Popen([binary, "-d", str(root), "-f", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.addCleanup(lambda: process.wait(timeout=5))
                self.addCleanup(process.terminate)
                return process

            landing = start_core("landing", {"listeners": [{"name": "landing", "type": "shadowsocks", "listen": "127.0.0.1", "port": entry.landing[1], "cipher": "aes-128-gcm", "password": password}], "rules": ["MATCH,DIRECT"]})
            conf = ClashMetaConfiguration()
            conf.add("Landing", "127.0.0.1", {"protocol": "shadowsocks", "port": entry.landing[1], "network": "tcp", "tls": "none", "sni": "", "host": "", "path": "", "header_type": "none"}, {"method": "aes-128-gcm", "password": password})
            node = {"name": "Entry", "type": "socks5", "server": "127.0.0.1", "port": entry.server_address[1]}
            key = entry_key(node)
            conf.data["proxies"][0]["dialer-proxy"] = key
            conf.cascade_entries[key] = node
            document = yaml.safe_load(conf.render(is_meta=True, secure_dns=False))
            document.update({"mixed-port": local_port, "mode": "rule", "proxy-groups": [], "rules": ["MATCH,Landing"]})
            client = start_core("client", document)
            deadline = time.monotonic() + 5
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", local_port), timeout=.1):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        self.fail("Mihomo did not start its local proxy")
                    time.sleep(.05)
            request = http.client.HTTPConnection("127.0.0.1", local_port, timeout=5)
            request.request("GET", f"http://127.0.0.1:{target.server_port}/")
            self.assertEqual(request.getresponse().read(), b"two-hop-route-confirmed")
            request.close()
            self.assertEqual(entry.hops, [entry.landing])
            # Removing the entry must not turn this into a direct landing route.
            entry.shutdown(); entry.server_close()
            request = http.client.HTTPConnection("127.0.0.1", local_port, timeout=5)
            request.request("GET", f"http://127.0.0.1:{target.server_port}/")
            self.assertGreaterEqual(request.getresponse().status, 400)
            request.close()
            self.assertIsNone(landing.poll()); self.assertIsNone(client.poll())
