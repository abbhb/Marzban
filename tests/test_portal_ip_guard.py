"""Host blacklist synchronizer tests without touching the real firewall."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

from scripts import portal_ip_guard


class FakeNftRunner:
    def __init__(self, *, table: bool, complete: bool = True) -> None:
        self.table = table
        self.complete = complete
        self.applied = []

    def table_exists(self) -> bool:
        return self.table

    def exists(self, _object_type: str, _name: str) -> bool:
        return self.table and self.complete

    def apply(self, ruleset: str) -> None:
        self.applied.append(ruleset)
        if "table inet marzban_portal_guard" in ruleset:
            self.table = True
            self.complete = True


class PortalIPGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="portal-ip-guard-")
        self.addCleanup(self.tempdir.cleanup)
        self.database_path = Path(self.tempdir.name) / "db.sqlite3"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE portal_ip_blocks (
                    id INTEGER PRIMARY KEY,
                    network TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    expires_at TEXT
                )
                """
            )
            connection.commit()

    def insert(self, network: str, *, active: bool = True, expires_at=None) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO portal_ip_blocks(network, is_active, expires_at) VALUES (?, ?, ?)",
                (network, int(active), expires_at),
            )
            connection.commit()

    def test_policy_read_filters_expired_and_collapses_networks(self) -> None:
        self.insert("203.0.113.0/25")
        self.insert("203.0.113.128/25")
        self.insert("198.51.100.1/32", active=False)
        self.insert("192.0.2.8/32", expires_at="2026-07-13 23:59:59")
        self.insert("2001:db8::/64")
        self.insert("2001:db8::1/128")

        ipv4, ipv6 = portal_ip_guard.load_active_networks(
            str(self.database_path),
            now=datetime(2026, 7, 14, 0, 0, 0),
        )

        self.assertEqual(("203.0.113.0/24",), ipv4)
        self.assertEqual(("2001:db8::/64",), ipv6)

    def test_invalid_database_policy_preserves_the_previous_firewall_state(self) -> None:
        self.insert("not-a-network")
        runner = FakeNftRunner(table=True)
        guard = portal_ip_guard.PortalIPGuard(
            database_path=str(self.database_path),
            runner=runner,
        )

        with self.assertRaises(portal_ip_guard.DatabasePolicyError):
            guard.sync_once()
        self.assertEqual([], runner.applied)

    def test_first_sync_creates_a_dedicated_non_timeout_table(self) -> None:
        self.insert("203.0.113.8")
        self.insert("2001:db8::8")
        runner = FakeNftRunner(table=False)
        guard = portal_ip_guard.PortalIPGuard(
            database_path=str(self.database_path),
            port=443,
            runner=runner,
            clock=lambda: datetime(2026, 7, 14),
        )

        self.assertEqual((1, 1), guard.sync_once())
        self.assertEqual(1, len(runner.applied))
        ruleset = runner.applied[0]
        self.assertIn("table inet marzban_portal_guard", ruleset)
        self.assertIn("203.0.113.8/32", ruleset)
        self.assertIn("2001:db8::8/128", ruleset)
        self.assertIn("tcp dport 443", ruleset)
        self.assertIn('iifname "lo" accept', ruleset)
        self.assertNotIn("timeout", ruleset)

    def test_periodic_sync_atomically_flushes_and_repopulates_both_sets(self) -> None:
        self.insert("203.0.113.0/24")
        runner = FakeNftRunner(table=True)
        guard = portal_ip_guard.PortalIPGuard(
            database_path=str(self.database_path),
            runner=runner,
            clock=lambda: datetime(2026, 7, 14),
        )

        guard.sync_once()
        runner.applied.clear()
        self.assertEqual((1, 0), guard.sync_once())
        self.assertEqual(1, len(runner.applied))
        transaction = runner.applied[0]
        self.assertIn("flush set inet marzban_portal_guard blocked_v4", transaction)
        self.assertIn("flush set inet marzban_portal_guard blocked_v6", transaction)
        self.assertIn("add element inet marzban_portal_guard blocked_v4", transaction)
        self.assertNotIn("delete table", transaction)
        self.assertNotIn("timeout", transaction)

    def test_partial_dedicated_table_is_replaced_in_one_transaction(self) -> None:
        runner = FakeNftRunner(table=True, complete=False)
        guard = portal_ip_guard.PortalIPGuard(
            database_path=str(self.database_path),
            runner=runner,
            clock=lambda: datetime(2026, 7, 14),
        )

        guard.sync_once()
        self.assertIn("delete table inet marzban_portal_guard", runner.applied[0])
        self.assertIn("table inet marzban_portal_guard", runner.applied[0])


if __name__ == "__main__":
    unittest.main()
