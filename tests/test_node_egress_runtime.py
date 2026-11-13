"""Opt-in TCP egress checks using the binary installed on a managed node.

Set XRAY_EGRESS_BINARY, XRAY_EGRESS_IPV6 and XRAY_EGRESS_IPV4 on a dual-stack
test host. Set XRAY_EGRESS_TRANSPORTS to a comma-separated subset if a core
does not serve every protocol. Requires curl and openssl. The test uses only
loopback listeners and disposable accounts. Cloudflare trace reports the
remote address. For REALITY, www.cloudflare.com also serves as the TLS target.
"""
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import uuid

DOMAIN = "www.cloudflare.com"
TRANSPORTS = ("vision", "xhttp", "relay-tls", "hysteria2")


def reserve_ports(count):
    # Reserve both transports since Hysteria uses UDP for the landing port.
    with contextlib.ExitStack() as stack:
        ports = []
        while len(ports) < count:
            tcp = stack.enter_context(socket.socket())
            tcp.bind(("127.0.0.1", 0))
            port = tcp.getsockname()[1]
            udp = stack.enter_context(socket.socket(type=socket.SOCK_DGRAM))
            try:
                udp.bind(("127.0.0.1", port))
            except OSError:
                continue
            ports.append(port)
        return ports


def streams(transport, binary, directory):
    if transport == "vision":
        keys = dict(line.split(": ", 1) for line in subprocess.check_output(
            [binary, "x25519"], text=True).splitlines() if ": " in line)
        public = keys.get("Password (PublicKey)") or keys.get("PublicKey") or keys.get("Password")
        if not public:
            raise ValueError("Xray did not report a public key")
        return (
            {"network": "tcp", "security": "reality", "realitySettings": {
                "target": f"{DOMAIN}:443", "serverNames": [DOMAIN],
                "privateKey": keys["PrivateKey"], "shortIds": ["ab01"]}},
            {"network": "tcp", "security": "reality", "realitySettings": {
                "serverName": DOMAIN, "fingerprint": "chrome", "publicKey": public,
                "shortId": "ab01"}},
        )
    if transport == "xhttp":
        stream = {"network": "xhttp", "xhttpSettings": {"path": "/probe", "mode": "packet-up"}}
        return stream, stream
    cert, key = str(directory / "cert.pem"), str(directory / "key.pem")
    server_tls = {"certificates": [{"certificateFile": cert, "keyFile": key}]}
    client_tls = {"serverName": "localhost", "certificates": [
        {"certificateFile": cert, "usage": "verify"}]}
    network = "tcp" if transport == "relay-tls" else "hysteria"
    if network == "hysteria":
        server_tls["alpn"] = client_tls["alpn"] = ["h3"]
    return ({"network": network, "security": "tls", "tlsSettings": server_tls},
            {"network": network, "security": "tls", "tlsSettings": client_tls})


def config_for(transport, binary, directory, ports, ipv6):
    server_stream, client_stream = streams(transport, binary, directory)
    hy2 = transport == "hysteria2"
    protocol = "hysteria" if hy2 else "vless"
    accounts = []
    server_settings = {"clients": accounts, **({"version": 2} if hy2 else {"decryption": "none"})}
    if hy2:
        server_stream["hysteriaSettings"] = {"version": 2}
    inbounds = [{"tag": "landing", "listen": "127.0.0.1", "port": ports[0],
                 "protocol": protocol, "settings": server_settings, "streamSettings": server_stream}]
    outbounds = [{"tag": "reject", "protocol": "blackhole"}]
    rules = []
    for port, family in zip(ports[1:], (6, 4)):
        tag = f"client-{family}"
        email = f"{tag}@example.test"
        credential = str(uuid.uuid4())
        stream = client_stream.copy()
        if hy2:
            accounts.append({"auth": credential, "email": email})
            settings = {"address": "127.0.0.1", "port": ports[0], "version": 2}
            stream["hysteriaSettings"] = {"version": 2, "auth": credential}
        else:
            account = {"id": credential}
            if transport == "vision":
                account["flow"] = "xtls-rprx-vision"
            accounts.append({**account, "email": email})
            settings = {"vnext": [{"address": "127.0.0.1", "port": ports[0],
                                   "users": [{**account, "encryption": "none"}]}]}
        inbounds.append({"tag": tag, "listen": "127.0.0.1", "port": port, "protocol": "socks"})
        outbounds.append({"tag": tag, "protocol": protocol, "settings": settings, "streamSettings": stream})
        direct = f"direct-{family}"
        outbounds.append({"tag": direct, "protocol": "freedom",
                          "settings": {"domainStrategy": f"ForceIPv{family}"},
                          **({"sendThrough": str(ipv6)} if family == 6 else {})})
        destination = {"type": "field", "domain": [f"full:{DOMAIN}"], "port": 443}
        rules.extend([{**destination, "inboundTag": [tag], "outboundTag": tag},
                      {**destination, "inboundTag": ["landing"], "user": [email], "outboundTag": direct}])
    return {"log": {"loglevel": "warning"}, "dns": {"servers": ["localhost"]},
            "inbounds": inbounds, "outbounds": outbounds, "routing": {"rules": rules}}


@unittest.skipUnless(all(os.getenv(k) for k in ("XRAY_EGRESS_BINARY", "XRAY_EGRESS_IPV6", "XRAY_EGRESS_IPV4")),
                     "Requires real Xray and expected node egress addresses")
class NodeEgressRuntimeTests(unittest.TestCase):
    def test_authenticated_tcp_egress(self):
        binary = os.environ["XRAY_EGRESS_BINARY"]
        ipv6 = ipaddress.IPv6Address(os.environ["XRAY_EGRESS_IPV6"])
        ipv4 = ipaddress.IPv4Address(os.environ["XRAY_EGRESS_IPV4"])
        selected = os.getenv("XRAY_EGRESS_TRANSPORTS", ",".join(TRANSPORTS)).split(",")
        self.assertTrue(set(selected) <= set(TRANSPORTS))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            subprocess.run(["openssl", "req", "-x509", "-nodes", "-newkey", "ec",
                            "-pkeyopt", "ec_paramgen_curve:P-256", "-days", "1", "-keyout", str(directory / "key.pem"),
                            "-out", str(directory / "cert.pem"), "-subj", "/CN=localhost",
                            "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
            for transport in selected:
                with self.subTest(transport=transport):
                    ports = reserve_ports(3)
                    config = config_for(transport, binary, directory, ports, ipv6)
                    path = directory / "config.json"
                    path.write_text(json.dumps(config))
                    with subprocess.Popen([binary, "run", "-c", str(path)], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL) as core:
                        try:
                            for _ in range(100):
                                self.assertIsNone(core.poll(), "Test Xray exited during startup")
                                try:
                                    with socket.create_connection(("127.0.0.1", ports[1]), timeout=.1):
                                        break
                                except OSError:
                                    time.sleep(.05)
                            else:
                                self.fail("Test Xray did not accept a loopback connection")
                            for port, expected in zip(ports[1:], (ipv6, ipv4)):
                                trace = subprocess.check_output([
                                    "curl", "--disable", "--fail", "--silent", "--show-error", "--noproxy", "",
                                    "--max-time", "12", "--socks5-hostname", f"127.0.0.1:{port}",
                                    f"https://{DOMAIN}/cdn-cgi/trace"], text=True)
                                fields = dict(s.split("=", 1) for s in trace.splitlines() if "=" in s)
                                self.assertEqual(ipaddress.ip_address(fields["ip"]), expected)
                        finally:
                            core.terminate()
                            try:
                                core.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                core.kill()


if __name__ == "__main__":
    unittest.main()
