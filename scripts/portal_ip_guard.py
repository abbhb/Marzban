#!/usr/bin/env python3
"""Synchronize Marzban's active portal blacklist into a dedicated nftables set.

The application database remains the source of truth.  This host-side process
periodically replaces the contents of two non-timeout interval sets.  A failed
database read or nft transaction leaves the last successfully applied policy in
place and is retried on the next interval.
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import signal
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple, Union


LOGGER = logging.getLogger("marzban-portal-ip-guard")
NFT_TABLE = "marzban_portal_guard"
NFT_FAMILY = "inet"
NFT_V4_SET = "blocked_v4"
NFT_V6_SET = "blocked_v6"
NFT_CHAIN = "input"


class GuardError(RuntimeError):
    """Base error for a failed policy read or firewall transaction."""


class DatabasePolicyError(GuardError):
    pass


class NftTransactionError(GuardError):
    pass


def utc_naive(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def parse_database_datetime(value: object) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return utc_naive(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return utc_naive(datetime.fromisoformat(text))
    except ValueError as exc:
        raise DatabasePolicyError("blacklist contains an invalid expiry timestamp") from exc


IPNetwork = Union[IPv4Network, IPv6Network]


def _collapse(networks: Sequence[IPNetwork]) -> Tuple[str, ...]:
    return tuple(str(network) for network in ipaddress.collapse_addresses(networks))


def load_active_networks(
    database_path: str,
    *,
    now: Optional[datetime] = None,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Read, validate and collapse currently effective blacklist networks."""

    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise DatabasePolicyError("portal SQLite database is unavailable")
    uri = f"{path.as_uri()}?mode=ro"
    current_time = utc_naive(now)
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT network, expires_at FROM portal_ip_blocks WHERE is_active = 1"
        ).fetchall()
    except sqlite3.Error as exc:
        raise DatabasePolicyError("unable to read portal IP blacklist") from exc
    finally:
        if "connection" in locals():
            connection.close()

    ipv4 = []
    ipv6 = []
    for raw_network, raw_expiry in rows:
        expiry = parse_database_datetime(raw_expiry)
        if expiry is not None and expiry <= current_time:
            continue
        try:
            network = ipaddress.ip_network(str(raw_network).strip(), strict=False)
        except ValueError as exc:
            raise DatabasePolicyError("blacklist contains an invalid IP network") from exc
        (ipv4 if network.version == 4 else ipv6).append(network)
    return _collapse(ipv4), _collapse(ipv6)


class NftRunner:
    def __init__(self, binary: str = "/usr/sbin/nft") -> None:
        self.binary = binary

    def run(self, arguments: Sequence[str], *, input_text: Optional[str] = None) -> int:
        try:
            result = subprocess.run(
                [self.binary, *arguments],
                input=input_text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10.0,
            )
        except OSError as exc:
            raise NftTransactionError("unable to execute nft") from exc
        except subprocess.TimeoutExpired as exc:
            raise NftTransactionError("nft command timed out") from exc
        return result.returncode

    def exists(self, object_type: str, name: str) -> bool:
        return self.run(["list", object_type, NFT_FAMILY, NFT_TABLE, name]) == 0

    def table_exists(self) -> bool:
        return self.run(["list", "table", NFT_FAMILY, NFT_TABLE]) == 0

    def apply(self, ruleset: str) -> None:
        if self.run(["-f", "-"], input_text=ruleset) != 0:
            raise NftTransactionError("nftables rejected the portal blacklist transaction")


def _set_block(name: str, address_type: str, networks: Sequence[str]) -> str:
    elements = f"        elements = {{ {', '.join(networks)} }}\n" if networks else ""
    return (
        f"    set {name} {{\n"
        f"        type {address_type}\n"
        "        flags interval\n"
        f"{elements}"
        "    }\n"
    )


def render_table(
    ipv4_networks: Sequence[str],
    ipv6_networks: Sequence[str],
    *,
    port: int,
    delete_existing: bool,
) -> str:
    prefix = f"delete table {NFT_FAMILY} {NFT_TABLE}\n" if delete_existing else ""
    return (
        f"{prefix}table {NFT_FAMILY} {NFT_TABLE} {{\n"
        f"{_set_block(NFT_V4_SET, 'ipv4_addr', ipv4_networks)}"
        f"{_set_block(NFT_V6_SET, 'ipv6_addr', ipv6_networks)}"
        f"    chain {NFT_CHAIN} {{\n"
        "        type filter hook input priority -10; policy accept;\n"
        '        iifname "lo" accept comment "preserve local recovery"\n'
        f"        tcp dport {port} ip saddr @{NFT_V4_SET} counter drop "
        'comment "Marzban portal IPv4 blacklist"\n'
        f"        tcp dport {port} ip6 saddr @{NFT_V6_SET} counter drop "
        'comment "Marzban portal IPv6 blacklist"\n'
        "    }\n"
        "}\n"
    )


def render_set_sync(
    ipv4_networks: Sequence[str],
    ipv6_networks: Sequence[str],
) -> str:
    lines = [
        f"flush set {NFT_FAMILY} {NFT_TABLE} {NFT_V4_SET}",
        f"flush set {NFT_FAMILY} {NFT_TABLE} {NFT_V6_SET}",
    ]
    if ipv4_networks:
        lines.append(
            f"add element {NFT_FAMILY} {NFT_TABLE} {NFT_V4_SET} "
            f"{{ {', '.join(ipv4_networks)} }}"
        )
    if ipv6_networks:
        lines.append(
            f"add element {NFT_FAMILY} {NFT_TABLE} {NFT_V6_SET} "
            f"{{ {', '.join(ipv6_networks)} }}"
        )
    return "\n".join(lines) + "\n"


class PortalIPGuard:
    def __init__(
        self,
        *,
        database_path: str,
        port: int = 443,
        runner: Optional[NftRunner] = None,
        clock: Callable[[], datetime] = utc_naive,
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self.database_path = database_path
        self.port = port
        self.runner = runner or NftRunner()
        self.clock = clock
        self.last_policy: Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]] = None
        self._initialized = False

    def _structure_exists(self, *, table_exists: bool) -> bool:
        return (
            table_exists
            and self.runner.exists("set", NFT_V4_SET)
            and self.runner.exists("set", NFT_V6_SET)
            and self.runner.exists("chain", NFT_CHAIN)
        )

    def sync_once(self) -> Tuple[int, int]:
        ipv4_networks, ipv6_networks = load_active_networks(
            self.database_path,
            now=self.clock(),
        )
        table_exists = self.runner.table_exists()
        if self._initialized and self._structure_exists(table_exists=table_exists):
            self.runner.apply(render_set_sync(ipv4_networks, ipv6_networks))
        else:
            self.runner.apply(
                render_table(
                    ipv4_networks,
                    ipv6_networks,
                    port=self.port,
                    delete_existing=table_exists,
                )
            )
        self.last_policy = (ipv4_networks, ipv6_networks)
        self._initialized = True
        return len(ipv4_networks), len(ipv6_networks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Marzban SQLite database path")
    parser.add_argument("--port", type=int, default=443, help="host TCP port to protect")
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="seconds between reconciliations (1-3600)",
    )
    parser.add_argument("--once", action="store_true", help="synchronize once and exit")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.interval <= 3600:
        raise SystemExit("--interval must be between 1 and 3600")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    guard = PortalIPGuard(database_path=args.database, port=args.port)
    if args.once:
        ipv4_count, ipv6_count = guard.sync_once()
        LOGGER.info("synchronized ipv4=%d ipv6=%d", ipv4_count, ipv6_count)
        return 0

    stopped = threading.Event()

    def stop(_signum, _frame) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped.is_set():
        try:
            previous_policy = guard.last_policy
            ipv4_count, ipv6_count = guard.sync_once()
            if guard.last_policy != previous_policy:
                LOGGER.info("synchronized ipv4=%d ipv6=%d", ipv4_count, ipv6_count)
        except GuardError as exc:
            LOGGER.error("synchronization failed: %s; retaining last applied policy", exc)
        stopped.wait(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
