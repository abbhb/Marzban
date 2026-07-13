"""Regression tests for remote-node health-check recovery decisions."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import app
from app.xray.node import NodeAPIError, NodeSessionError


def _event_handler(event_handlers, name):
    return next(handler for handler in event_handlers if handler.__name__ == name)


START_CORE = _event_handler(app.router.on_startup, "start_core")
APP_SHUTDOWN = _event_handler(app.router.on_shutdown, "app_shutdown")
HEALTH_GLOBALS = START_CORE.__globals__
CORE_HEALTH_CHECK = HEALTH_GLOBALS["core_health_check"]


class FakeNodeAPI:
    def __init__(self):
        self.error = None
        self.timeouts = []

    def get_sys_stats(self, timeout):
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return {"ok": True}


class FakeNode:
    address = "node.example"

    def __init__(self):
        self.connection_error = None
        self.started_error = None
        self.is_connected = True
        self.is_started = True
        self.connection_timeouts = []
        self.started_timeouts = []
        self.api = FakeNodeAPI()
        self.disconnect = Mock()

    def check_connection(self, timeout):
        self.connection_timeouts.append(timeout)
        if self.connection_error:
            raise self.connection_error
        return self.is_connected

    def check_started(self, timeout):
        self.started_timeouts.append(timeout)
        if self.started_error:
            raise self.started_error
        return self.is_started


def fake_xray(node):
    return SimpleNamespace(
        core=SimpleNamespace(started=True, restart=Mock(), stop=Mock()),
        config=SimpleNamespace(include_db_users=Mock(return_value="generated-config")),
        nodes={7: node},
        operations=SimpleNamespace(restart_node=Mock(), connect_node=Mock()),
    )


class NodeHealthCheckTests(unittest.TestCase):
    def setUp(self):
        self.node = FakeNode()
        self.xray = fake_xray(self.node)
        self.health_globals = patch.dict(
            HEALTH_GLOBALS,
            {
                "xray": self.xray,
                "JOB_CORE_HEALTH_CHECK_INTERVAL": 60,
                "JOB_CORE_HEALTH_CHECK_TIMEOUT": 5,
                "JOB_CORE_HEALTH_CHECK_FAILURE_THRESHOLD": 2,
            },
        )
        self.health_globals.start()
        self.addCleanup(self.health_globals.stop)
        HEALTH_GLOBALS["_node_health_failures"].clear()

    def tearDown(self):
        HEALTH_GLOBALS["_node_health_failures"].clear()

    def run_health_check(self, times=1):
        for _ in range(times):
            CORE_HEALTH_CHECK()

    def test_all_remote_probes_use_five_second_timeout(self):
        self.run_health_check()

        self.assertEqual([5], self.node.connection_timeouts)
        self.assertEqual([5], self.node.started_timeouts)
        self.assertEqual([5], self.node.api.timeouts)

    def test_stats_failure_restarts_only_after_two_consecutive_cycles(self):
        self.node.api.error = ConnectionError("gRPC stats timed out")

        self.run_health_check()
        self.xray.operations.restart_node.assert_not_called()

        self.run_health_check()
        self.xray.operations.restart_node.assert_called_once()
        args, kwargs = self.xray.operations.restart_node.call_args
        self.assertEqual((7, "generated-config"), args)
        self.assertIn("failure=stats_unavailable", kwargs["reason"])
        self.assertIn("consecutive_failures=2", kwargs["reason"])
        self.assertIn("interval=60s", kwargs["reason"])
        self.assertIn("timeout=5s", kwargs["reason"])

    def test_control_plane_failure_never_restarts_remote_data_plane(self):
        self.node.connection_error = NodeAPIError(0, "SSH tunnel refused connection")

        self.run_health_check(times=3)

        self.xray.operations.restart_node.assert_not_called()
        self.xray.operations.connect_node.assert_not_called()
        self.xray.config.include_db_users.assert_not_called()

    def test_invalid_session_reconnects_after_two_consecutive_cycles(self):
        self.node.connection_error = NodeSessionError(0, "session missing")

        self.run_health_check()
        self.xray.operations.connect_node.assert_not_called()

        self.run_health_check()
        self.xray.operations.connect_node.assert_called_once()
        _, kwargs = self.xray.operations.connect_node.call_args
        self.assertIn("failure=session_invalid", kwargs["reason"])

    def test_failure_category_change_restarts_consecutive_count(self):
        self.node.is_started = False
        self.run_health_check()

        self.node.is_started = True
        self.node.api.error = ConnectionError("stats timeout")
        self.run_health_check()

        self.xray.operations.restart_node.assert_not_called()
        state = HEALTH_GLOBALS["_node_health_failures"][7]
        self.assertEqual("stats_unavailable", state["kind"])
        self.assertEqual(1, state["count"])

    def test_successful_cycle_clears_failure_streak(self):
        self.node.is_started = False
        self.run_health_check()
        self.node.is_started = True

        self.run_health_check()

        self.assertNotIn(7, HEALTH_GLOBALS["_node_health_failures"])
        self.xray.operations.restart_node.assert_not_called()

    def test_panel_shutdown_does_not_disconnect_remote_node(self):
        APP_SHUTDOWN()

        self.xray.core.stop.assert_called_once_with()
        self.node.disconnect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
