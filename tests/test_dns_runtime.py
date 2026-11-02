"""Optional real-core fake-IP matching checks with loopback-only DNS upstreams.

Run with MIHOMO_TEST_BINARY=/path/to/mihomo. No TUN or public DNS is used.
"""
import ipaddress
import os
from pathlib import Path
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import unittest

import yaml

from app.subscription.dns_security import secure_mihomo_dns


REAL_ADDRESS = "203.0.113.42"
HOST_ADDRESS = "198.51.100.11"
FAKE_RANGE = ipaddress.ip_network("198.18.0.0/16")


def skip_name(packet, offset):
    while packet[offset]:
        if packet[offset] & 0xc0 == 0xc0:
            return offset + 2
        offset += packet[offset] + 1
    return offset + 1


class Upstream(socketserver.BaseRequestHandler):
    def handle(self):
        packet, connection = self.request
        end = skip_name(packet, 12)
        question = packet[12:end + 4]
        labels = []
        offset = 12
        while packet[offset]:
            size = packet[offset]
            labels.append(packet[offset + 1:offset + size + 1].decode())
            offset += size + 1
        self.server.queries.append(".".join(labels).lower())
        header = packet[:2] + struct.pack("!5H", 0x8180, 1, 1, 0, 0)
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton(REAL_ADDRESS)
        connection.sendto(header + question + answer, self.client_address)


@unittest.skipUnless(os.environ.get("MIHOMO_TEST_BINARY"), "Set MIHOMO_TEST_BINARY to test the real core")
class DnsRuntimeTests(unittest.TestCase):
    def setUp(self):
        upstream = socketserver.UDPServer(("127.0.0.1", 0), Upstream)
        upstream.queries = []
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        self.upstream = upstream
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        value = {
            "log-level": "error",
            "hosts": {"override.localdomain": HOST_ADDRESS},
            "proxies": [{"name": "allowed", "type": "ss", "server": "127.0.0.1", "port": 9,
                         "cipher": "aes-128-gcm", "password": "dns-test-only"}],
            "proxy-groups": [{"name": "primary", "type": "select", "proxies": ["allowed"]}],
            "rules": ["MATCH,primary"],
        }
        secure_mihomo_dns(value, "primary", "")
        # Exercise the generated filter with a deterministic local resolver.
        # Production resolver routing is covered separately by test_dns_security.
        resolver = f"udp://127.0.0.1:{upstream.server_address[1]}#DIRECT"
        value["dns"].update({
            "listen": f"127.0.0.1:{self.port}",
            "nameserver": [resolver],
            "default-nameserver": [resolver],
            "proxy-server-nameserver": [resolver],
        })
        value["tun"]["enable"] = False
        temporary = tempfile.TemporaryDirectory(prefix="mihomo-dns-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config = root / "config.yaml"
        config.write_text(yaml.safe_dump(value, allow_unicode=True))
        binary = os.environ["MIHOMO_TEST_BINARY"]
        checked = subprocess.run(
            [binary, "-t", "-d", str(root), "-f", str(config)], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        log = (root / "core.log").open("w+")
        self.addCleanup(log.close)
        process = subprocess.Popen([binary, "-d", str(root), "-f", str(config)], stdout=log, stderr=subprocess.STDOUT)
        self.addCleanup(self.stop_core, process)
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                log.seek(0)
                self.fail("Test core exited: " + log.read())
            try:
                self.query("startup.example.net")
                break
            except OSError:
                if time.monotonic() >= deadline:
                    self.fail("Test core DNS did not start")
                time.sleep(0.05)

    @staticmethod
    def stop_core(process):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def query(self, name):
        question = b"".join(bytes([len(label)]) + label.encode() for label in name.split(".")) + b"\0\0\1\0\1"
        transaction = os.urandom(2)
        packet = transaction + struct.pack("!5H", 0x0100, 1, 0, 0, 0) + question
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.settimeout(0.5)
            connection.sendto(packet, ("127.0.0.1", self.port))
            response, _ = connection.recvfrom(4096)
        self.assertEqual(response[:2], transaction)
        _, flags, questions, answers, _, _ = struct.unpack("!6H", response[:12])
        self.assertEqual(flags & 0x0f, 0)
        offset = 12
        for _ in range(questions):
            offset = skip_name(response, offset) + 4
        addresses = []
        for _ in range(answers):
            offset = skip_name(response, offset)
            kind, _, _, length = struct.unpack("!HHIH", response[offset:offset + 10])
            offset += 10
            if kind == 1 and length == 4:
                addresses.append(socket.inet_ntoa(response[offset:offset + length]))
            offset += length
        self.assertTrue(addresses, "No A record for " + name)
        return addresses

    def test_compatibility_names_resolve_real_ips_through_the_upstream(self):
        for name in (
            "printer.lan", "nas.localdomain", "router.home.arpa", "WORKGROUP",
            "time.apple.com", "time-ios.apple.com", "time7.example.com", "ntp7.example.com",
            "clock.time.edu.cn", "cn.pool.ntp.org", "pool.ntp.org",
            "stun.l.google.com", "stun.example.com", "a.stun.deep.example.net",
            "stun.playstation.net", "www.msftconnecttest.com", "msftncsi.com",
            "localhost.ptlogin2.qq.com", "localhost.sec.qq.com",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.query(name), [REAL_ADDRESS])
                self.assertIn(name.lower(), self.upstream.queries)

    def test_normal_domains_keep_fake_ips_and_do_not_hit_the_upstream(self):
        for name in ("www.qq.com", "v.qq.com", "www.tencent.com", "video.nflxvideo.net",
                     "www.netflix.com", "music.163.com", "www.youtube.com", "www.example.net"):
            with self.subTest(name=name):
                self.assertTrue(all(ipaddress.ip_address(address) in FAKE_RANGE for address in self.query(name)))
                self.assertNotIn(name, self.upstream.queries)

    def test_hosts_override_is_answered_without_a_dns_lookup(self):
        self.assertEqual(self.query("override.localdomain"), [HOST_ADDRESS])
        self.assertNotIn("override.localdomain", self.upstream.queries)
