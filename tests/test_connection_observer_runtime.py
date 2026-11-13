"""Opt-in real-core verification using only disposable loopback connections.

Set XRAY_OBSERVER_BINARY to an Xray built with scripts/connection_observer.
No remote servers or production accounts are used.
"""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import uuid


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"observer-test-ok")

    def log_message(self, *args):
        pass


class IPv6HTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def port_for(host):
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.getenv("XRAY_OBSERVER_BINARY"), "Requires a connection-observing Xray binary")
class ConnectionObserverRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="marzban-observer-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.servers = {}
        for host, server_type in (("127.0.0.1", ThreadingHTTPServer), ("::1", IPv6HTTPServer)):
            try:
                server = server_type((host, 0), Handler)
            except OSError as error:
                self.skipTest(f"Loopback family unavailable: {error}")
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            self.servers[host] = server.server_port
        self.accounts = {name: str(uuid.uuid4()) for name in ("alice", "bob")}
        self.entries = {host: port_for(host) for host in self.servers}
        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"tag": f"entry-{ipaddress.ip_address(host).version}",
                          "listen": host, "port": port, "protocol": "vless",
                          "settings": {"decryption": "none", "clients": [
                              {"id": credential, "email": f"{index}.{name}"}
                              for index, (name, credential) in enumerate(self.accounts.items(), 1)]}}
                         for host, port in self.entries.items()],
            "outbounds": [{"tag": "direct", "protocol": "freedom", "settings": {
                "finalRules": [{"action": "allow", "network": "tcp",
                                "ip": ["127.0.0.1/32", "::1/128"],
                                "port": ",".join(str(port) for port in self.servers.values())}]}}],
        }
        self.config = config
        self.path = self.root / "config.json"
        self.log_path = self.root / "stdout.log"
        self.log = self.log_path.open("w")
        self.addCleanup(self.log.close)
        self.start()
        self.addCleanup(self.stop)

    def start(self, probe_port=None):
        self.path.write_text(json.dumps(self.config))
        self.process = subprocess.Popen([os.environ["XRAY_OBSERVER_BINARY"], "run", "-c", str(self.path)], stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            self.assertIsNone(self.process.poll(), self.log_path.read_text())
            try:
                with socket.create_connection(("127.0.0.1", probe_port or self.entries["127.0.0.1"]), timeout=.1):
                    return
            except OSError:
                time.sleep(.03)
        self.fail("Xray did not start")

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def request(self, entry, target, name, target_port=None):
        try:
            address = ipaddress.ip_address(target)
            destination = bytes([1 if address.version == 4 else 3]) + address.packed
        except ValueError:
            destination = b"\x02" + bytes([len(target)]) + target.encode("ascii")
        port = target_port or self.servers[target]
        header = b"\x00" + uuid.UUID(self.accounts[name]).bytes + b"\x00\x01" + port.to_bytes(2, "big") + destination
        with socket.create_connection((entry, self.entries[entry]), timeout=5) as conn:
            conn.sendall(header + b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            response = b""
            while True:
                data = conn.recv(16384)
                if not data:
                    break
                response += data
        self.assertIn(b"observer-test-ok", response)

    def events(self, expected):
        for _ in range(100):
            rows = [json.loads(line[len("MZCONN "):]) for line in self.log_path.read_text().splitlines() if line.startswith("MZCONN ")]
            rows = [row for row in rows if row.get("event") == "dial"]
            if len(rows) >= expected:
                return rows
            time.sleep(.02)
        self.fail("Missing actual dial observations")

    def test_real_ipv4_ipv6_cross_family_paths(self):
        for entry in self.entries:
            for target in self.servers:
                self.request(entry, target, "alice")
        rows = self.events(4)
        self.assertEqual(4, len(rows))
        expected = {(incoming, outgoing) for incoming in ("tcp:127.0.0.1:", "tcp:[::1]:") for outgoing in ("127.0.0.1:", "[::1]:")}
        actual = set()
        for row in rows:
            self.assertEqual("1.alice", row["user"])
            self.assertEqual("direct", row["outbound"])
            actual.add((next(prefix for prefix, _ in expected if row["source"].startswith(prefix)),
                        next(prefix for _, prefix in expected if row["remote"].startswith(prefix))))
        self.assertEqual(expected, actual)

    def test_concurrent_users_same_destination_remain_distinct(self):
        tasks = [(entry, target, name) for entry in self.entries for target in self.servers for name in self.accounts]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda args: self.request(*args), tasks))
        rows = self.events(len(tasks))
        self.assertEqual(len(tasks), len(rows))
        self.assertEqual({"1.alice": 4, "2.bob": 4}, {identity: sum(row["user"] == identity for row in rows) for identity in ("1.alice", "2.bob")})
        self.assertEqual(len(rows), len({row["id"] for row in rows}))

    def test_ipv6_preference_records_only_the_successful_ipv4_fallback(self):
        self.stop()
        self.config["dns"] = {"hosts": {"observer.test": ["::1", "127.0.0.1"]}}
        self.config["outbounds"][0]["streamSettings"] = {"sockopt": {
            "domainStrategy": "ForceIP", "happyEyeballs": {
                "tryDelayMs": 40, "prioritizeIPv6": True, "interleave": 1, "maxConcurrentTry": 2}}}
        self.start()
        self.request("127.0.0.1", "observer.test", "alice", self.servers["127.0.0.1"])
        rows = self.events(1)
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["remote"].startswith("127.0.0.1:"))
        self.assertTrue(rows[0]["target"].startswith("tcp:observer.test:"))

    @unittest.skipUnless(shutil.which("curl") and shutil.which("openssl"), "Requires curl and openssl")
    def test_xhttp_and_hysteria2_preserve_user_context_at_actual_egress(self):
        from tests.test_node_egress_runtime import streams
        self.stop()
        binary = os.environ["XRAY_OBSERVER_BINARY"]
        subprocess.run(["openssl", "req", "-x509", "-nodes", "-newkey", "ec",
                        "-pkeyopt", "ec_paramgen_curve:P-256", "-days", "1", "-keyout", str(self.root / "key.pem"),
                        "-out", str(self.root / "cert.pem"), "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
        for transport in ("xhttp", "hysteria2"):
            with self.subTest(transport=transport):
                self.log.seek(0); self.log.truncate()
                server_stream, client_stream = streams(transport, binary, self.root)
                hy2 = transport == "hysteria2"
                protocol = "hysteria" if hy2 else "vless"
                credential = self.accounts["alice"]
                if hy2:
                    accounts = [{"auth": credential, "email": "1.alice"}]
                    server_settings = {"version": 2, "clients": accounts}
                    server_stream["hysteriaSettings"] = {"version": 2}
                    client_stream["hysteriaSettings"] = {"version": 2, "auth": credential}
                    client_settings = {"address": "127.0.0.1", "port": self.entries["127.0.0.1"], "version": 2}
                else:
                    server_settings = {"decryption": "none", "clients": [{"id": credential, "email": "1.alice"}]}
                    client_settings = {"vnext": [{"address": "127.0.0.1", "port": self.entries["127.0.0.1"],
                                                  "users": [{"id": credential, "encryption": "none"}]}]}
                socks_port = port_for("127.0.0.1")
                self.config["inbounds"] = [
                    {"tag": "landing", "listen": "127.0.0.1", "port": self.entries["127.0.0.1"],
                     "protocol": protocol, "settings": server_settings, "streamSettings": server_stream},
                    {"tag": "socks", "listen": "127.0.0.1", "port": socks_port, "protocol": "socks"},
                ]
                self.config["outbounds"] = [self.config["outbounds"][0],
                    {"tag": "uplink", "protocol": protocol, "settings": client_settings, "streamSettings": client_stream}]
                self.config["routing"] = {"rules": [{"type": "field", "inboundTag": ["socks"], "outboundTag": "uplink"}]}
                self.start(probe_port=socks_port)
                try:
                    for target, port in self.servers.items():
                        url = f"http://{'[' + target + ']' if ':' in target else target}:{port}/"
                        result = subprocess.check_output(["curl", "--disable", "--noproxy", "", "--fail", "--silent", "--show-error",
                                                          "--max-time", "5", "--socks5-hostname", f"127.0.0.1:{socks_port}", url], text=True)
                        self.assertEqual("observer-test-ok", result)
                    rows = self.events(2)
                    self.assertEqual(2, len(rows))
                    self.assertTrue(all(row["user"] == "1.alice" and row["inbound"] == "landing" for row in rows))
                    self.assertTrue(any(row["remote"].startswith("127.0.0.1:") for row in rows))
                    self.assertTrue(any(row["remote"].startswith("[::1]:") for row in rows))
                finally:
                    self.stop()


if __name__ == "__main__":
    unittest.main()
