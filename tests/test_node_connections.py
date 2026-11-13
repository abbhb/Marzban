"""Identity and evidence boundaries for per-host socket observations."""

from collections import deque
from contextlib import contextmanager
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import get_db
from app.models.node import NodeResponse, NodeStatus
from app.routers import node as routes
from app.services.node_connections import ConnectionObservations, endpoint
from app.xray.node import ReSTXRayNode


def event(**changes):
    return {"version": 1, "event": "dial", "id": "dial-1",
            "timestamp": "2026-11-13T10:00:00Z", "user": "7.alice",
            "source": "tcp:192.0.2.5:1234", "target": "tcp:example.test:443",
            "network": "tcp", "inbound": "vless", "outbound": "mz6-a",
            "local": "[2001:db8::5]:45000", "remote": "[2001:db8::10]:443",
            **changes}


def line(**changes):
    return "MZCONN " + json.dumps(event(**changes))


class ConnectionEvidenceTests(unittest.TestCase):
    def test_all_four_paths_use_observed_socket_not_the_requested_hostname(self):
        for incoming in ("192.0.2.5:1234", "[2001:db8::5]:1234"):
            for outgoing in ("198.51.100.5:443", "[2001:db8::10]:443"):
                with self.subTest(incoming=incoming, outgoing=outgoing):
                    observations = ConnectionObservations()
                    observations.feed(line(source=incoming, remote=outgoing))
                    record = observations.snapshot()["records"][0]
                    self.assertEqual(endpoint(incoming)[1], record["source_family"])
                    self.assertEqual(endpoint(outgoing)[1], record["egress_family"])
                    self.assertEqual("alice", record["user"])
                    self.assertEqual("tcp:example.test:443", record["target"])
                    self.assertEqual("socket", record["evidence"])

    def test_concurrent_users_on_same_target_never_share_identity_or_family(self):
        observations = ConnectionObservations()
        observations.feed(line(id="alice", user="7.alice"))
        observations.feed(line(id="bob", user="8.bob", remote="198.51.100.5:443"))
        records = {row["user"]: row for row in observations.snapshot()["records"]}
        self.assertEqual("IPv6", records["alice"]["egress_family"])
        self.assertEqual("IPv4", records["bob"]["egress_family"])

    def test_plain_access_logs_never_prove_egress_even_for_ip_literal(self):
        observations = ConnectionObservations()
        observations.feed("2026/11/13 10:00:00 from 192.0.2.5:100 accepted tcp:[2001:db8::1]:443 [vless -> direct] email: 7.alice")
        row = observations.snapshot()["records"][0]
        self.assertEqual("alice", row["user"])
        self.assertEqual("direct", row["outbound"])
        self.assertIsNone(row["egress_family"])
        self.assertIsNone(row["remote_ip"])
        self.assertFalse(observations.observer)

    def test_observer_upgrades_exact_pending_request_and_keeps_unobserved_requests(self):
        observations = ConnectionObservations()
        access = "from 192.0.2.5:100 accepted tcp:example.test:443 [vless -> direct] email: 7.alice"
        observations.feed(access)
        observations.feed(access.replace("7.alice", "8.bob"))
        observations.feed('MZCONN {"version":1,"event":"ready"}')
        observations.feed(line(source="tcp:192.0.2.5:100", outbound="direct"))
        self.assertEqual(2, len(observations.records))
        self.assertEqual("socket", observations.records[0]["evidence"])
        self.assertEqual("bob", observations.records[1]["user"])
        self.assertIsNone(observations.records[1]["egress_family"])
        self.assertTrue(observations.observer)

    def test_retention_and_invalid_events_are_bounded(self):
        observations = ConnectionObservations(limit=2)
        observations.feed(line(id="one") + "\n" + line(id="two") + "\n" + line(id="three"))
        for invalid in ("MZCONN null", "MZCONN {bad", line(user=None), line(remote="example.test:443"), line(version=2), "x" * 20000):
            self.assertFalse(observations.feed(invalid))
        self.assertEqual(["three", "two"], [row["id"] for row in observations.records])

    def test_mapped_ipv4_and_unspecified_local_are_not_mislabelled_ipv6(self):
        self.assertEqual(("192.0.2.5", "IPv4"), endpoint("tcp:[::ffff:192.0.2.5]:443"))
        self.assertEqual((None, None), endpoint("[::]:45000"))


class ConnectionStreamTests(unittest.TestCase):
    def setUp(self):
        self.application = FastAPI()
        self.application.include_router(routes.router)
        self.db = Mock()
        self.application.dependency_overrides[get_db] = lambda: self.db
        self.closed = False

        @contextmanager
        def logs():
            try:
                yield deque([line()])
            finally:
                self.closed = True

        self.source = SimpleNamespace(get_logs=Mock(side_effect=logs), started=True, version="26.10.21")
        self.xray = SimpleNamespace(core=self.source, nodes={7: self.source})
        self.node = NodeResponse(id=7, name="node", address="example.test", status=NodeStatus.connected)
        self.patches = [
            patch.object(routes, "xray", self.xray),
            patch.object(routes.Admin, "get_admin", side_effect=lambda token, db: SimpleNamespace(is_sudo=token == "sudo") if token in ("sudo", "admin") else None),
            patch.object(routes.crud, "get_node", side_effect=lambda db, node_id: self.node if node_id == 7 else None),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(self.application)

    def test_sudo_streams_exact_host_and_releases_subscription_on_close(self):
        with self.client.websocket_connect("/api/node/7/connections") as socket:
            socket.send_json({"token": "sudo"})
            snapshot = socket.receive_json()
            self.assertEqual("alice", snapshot["records"][0]["user"])
            self.assertEqual("IPv6", snapshot["records"][0]["egress_family"])
        self.assertTrue(self.closed)
        self.source.get_logs.assert_called_once()

    def test_panel_core_uses_reserved_zero_and_its_own_logs(self):
        with self.client.websocket_connect("/api/node/0/connections") as socket:
            socket.send_json({"token": "sudo"})
            self.assertTrue(socket.receive_json()["observer"])
        routes.crud.get_node.assert_not_called()

    def test_host_streams_do_not_mix_records_from_another_node(self):
        @contextmanager
        def other_logs():
            yield deque([line(user="8.bob")])
        self.xray.nodes[8] = SimpleNamespace(get_logs=other_logs)
        with self.client.websocket_connect("/api/node/7/connections") as socket:
            socket.send_json({"token": "sudo"})
            self.assertEqual(["alice"], [row["user"] for row in socket.receive_json()["records"]])

    def test_service_catalog_includes_local_host_and_uses_delivery_scope(self):
        self.xray.config = SimpleNamespace(
            inbounds_by_tag={"shared": {}, "hy2": {}},
            has_inbound_on=lambda tag, node_id: (tag == "shared" and node_id is None) or (tag == "hy2" and node_id == 7),
        )
        with patch.object(routes.crud, "get_nodes", return_value=[self.node]):
            response = self.client.get("/api/node-services", headers={"Authorization": "Bearer sudo"})
        self.assertEqual(200, response.status_code)
        local, remote = response.json()
        self.assertEqual((0, ["shared"]), (local["id"], local["inbound_tags"]))
        self.assertEqual((7, ["hy2"]), (remote["id"], remote["inbound_tags"]))

    def test_auth_not_found_and_disconnected_fail_without_subscribing(self):
        for token, node_id, expected in (("bad", 7, 4401), ("admin", 7, 4403), ("sudo", 8, 4404)):
            with self.subTest(token=token, node_id=node_id), self.assertRaises(WebSocketDisconnect) as error:
                with self.client.websocket_connect(f"/api/node/{node_id}/connections") as socket:
                    socket.send_json({"token": token})
                    socket.receive_json()
            self.assertEqual(expected, error.exception.code)
        self.node.status = NodeStatus.disabled
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect("/api/node/7/connections") as socket:
                socket.send_json({"token": "sudo"})
                socket.receive_json()
        self.assertEqual(4400, error.exception.code)
        self.source.get_logs.assert_not_called()


class RemoteSubscriptionTests(unittest.TestCase):
    def test_closing_one_empty_buffer_preserves_the_other_subscriber(self):
        node = ReSTXRayNode.__new__(ReSTXRayNode)
        node._logs_queues = []
        node._logs_bg_thread = Mock()
        node._logs_bg_thread.is_alive.return_value = True
        first_context = node.get_logs()
        first = first_context.__enter__()
        with node.get_logs() as second:
            self.assertIsNot(first, second)
            self.assertEqual(first, second)
            first_context.__exit__(None, None, None)
            self.assertEqual(1, len(node._logs_queues))
            self.assertIs(second, node._logs_queues[0])
        self.assertEqual([], node._logs_queues)

    def test_remote_websocket_closes_when_last_subscriber_leaves(self):
        node = ReSTXRayNode.__new__(ReSTXRayNode)
        node._logs_queues = [deque()]
        node._logs_ws_url = "wss://example.test/logs"
        node._session_id = "test-session"
        node._ssl_context = Mock()
        node.session = SimpleNamespace(verify="test-cert")
        socket = Mock()
        socket.recv.side_effect = lambda: node._logs_queues.clear() or ""
        with patch("app.xray.node.create_connection", return_value=socket), patch("app.xray.node.time.sleep"):
            node._bg_fetch_logs()
        socket.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
