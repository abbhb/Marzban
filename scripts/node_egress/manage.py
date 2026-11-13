#!/usr/bin/env python3
"""Provision and reconcile one Linux Marzban-node instance (run as root)."""

import argparse
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from policy import new_mark, render, resolve_list


def command(args, data=None):
    result = subprocess.run(
        args, input=data, text=True, capture_output=True, timeout=25, check=False
    )
    if result.returncode:
        # Xray replies can include account configuration. Do not log payloads.
        raise RuntimeError(
            f"{Path(args[0]).name} {args[1]} failed ({result.returncode}): "
            + (
                result.stderr.strip()[:200]
                if args[0] in ("ip", "nft")
                else "check node service"
            )
        )
    return result.stdout


class Instance:
    def __init__(self, filename):
        conf = json.loads(filename.read_text())
        self.directory = filename.parent
        self.state = Path(conf["state"])
        self.binary = conf["binary"]
        self.dev = conf["interface"]
        self.prefix = ipaddress.IPv6Network(conf["prefix"], strict=True)
        self.tags = conf["inbounds"]
        self.namespace = conf["namespace"]
        if not re.fullmatch(r"[a-z0-9_]{1,20}", self.namespace) or not re.fullmatch(
            r"[a-zA-Z0-9_.-]{1,15}", self.dev
        ):
            raise ValueError("Invalid instance or interface")
        if self.prefix.prefixlen != 64 or not self.prefix.is_global or not self.tags:
            raise ValueError("A global /64 and at least one inbound are required")
        self.table = "mz6_" + self.namespace
        self.db = sqlite3.connect(self.directory / "allocations.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""CREATE TABLE IF NOT EXISTS users (
            identity TEXT PRIMARY KEY, mark INTEGER UNIQUE NOT NULL, address TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS owned (address TEXT PRIMARY KEY);""")

    def value(self, key, default=None):
        row = self.db.execute("select value from state where key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save(self, key, value):
        self.db.execute(
            "insert or replace into state values (?,?)", (key, json.dumps(value))
        )
        self.db.commit()

    def api(self, action, *args, data=None, reply=False):
        cmd = [
            self.binary,
            "api",
            action,
            "-s",
            "unix://" + str(self.state / "control.sock"),
            *args,
        ]
        if data is not None:
            cmd.append("stdin:")
        output = command(cmd, json.dumps(data) if data is not None else None)
        return json.loads(output) if reply else None

    def addresses(self):
        entries = json.loads(
            command(["ip", "-j", "-6", "address", "show", "dev", self.dev])
        )[0]
        return {a["local"]: a for a in entries["addr_info"]}

    def allocate(self, identity, reset=False):
        row = self.db.execute(
            "select * from users where identity=?", (identity,)
        ).fetchone()
        if row and not reset:
            return dict(row)
        if reset and not row:
            raise ValueError("Unknown user ID")
        existing = self.addresses()
        while True:
            addr = str(self.prefix.network_address + secrets.randbits(64))
            if (
                addr not in existing
                and not self.db.execute(
                    "select 1 from owned where address=?", (addr,)
                ).fetchone()
            ):
                break
        # Reserve persistent ownership before configuring the address. Each instance has its own reserved mark prefix.
        prefix = self.value("mark_prefix")
        mark = (
            row["mark"]
            if row
            else new_mark(
                prefix, {item[0] for item in self.db.execute("select mark from users")}
            )
        )
        with self.db:
            self.db.execute(
                "insert or replace into users values (?,?,?)", (identity, mark, addr)
            )
            self.db.execute("insert into owned values (?)", (addr,))
        return {"identity": identity, "mark": mark, "address": addr}

    def provision(self, rows):
        existing = self.addresses()
        for row in rows:
            addr = row["address"]
            if addr not in existing:
                command(
                    [
                        "ip",
                        "-6",
                        "addr",
                        "add",
                        addr + "/128",
                        "dev",
                        self.dev,
                        "preferred_lft",
                        "0",
                        "noprefixroute",
                    ]
                )
            elif existing[addr]["prefixlen"] != 128:
                raise RuntimeError("Address conflict on interface")
        for attempt in range(30):
            info = self.addresses()
            if any(info.get(r["address"], {}).get("dadfailed") for r in rows):
                raise RuntimeError("Duplicate IPv6 address detected")
            if all(
                r["address"] in info and not info[r["address"]].get("tentative")
                for r in rows
            ):
                # The first packet from a new /128 may wait for provider NDP
                # longer than Happy Eyeballs. Verify real return traffic before
                # exposing the new mapping, retrying after an interrupted sync.
                verified = set(self.value("verified_addresses", [])) & set(info)
                pending = [
                    r["address"]
                    for r in rows
                    if r["address"] not in verified or r["address"] not in existing
                ]
                if pending:

                    def verify(addr):
                        for host in (
                            "www.cloudflare.com",
                            "one.one.one.one",
                            "www.cloudflare.com",
                        ):
                            try:
                                trace = command(
                                    [
                                        "curl",
                                        "-q",
                                        "-6",
                                        "--noproxy",
                                        "*",
                                        "--interface",
                                        addr,
                                        "--fail",
                                        "--silent",
                                        "--max-time",
                                        "10",
                                        f"https://{host}/cdn-cgi/trace",
                                    ]
                                )
                            except RuntimeError:
                                continue
                            if "ip=" + addr in trace.splitlines():
                                return addr
                        raise RuntimeError("IPv6 source readback failed")

                    with ThreadPoolExecutor(max_workers=4) as pool:
                        verified.update(pool.map(verify, pending))
                    self.save("verified_addresses", sorted(verified))
                return
            time.sleep(0.15)
        raise RuntimeError("IPv6 addresses not ready")

    def nat(self, rows):
        tables = json.loads(command(["nft", "-j", "list", "tables"]))["nftables"]
        exists = any(
            x.get("table", {}).get("name") == self.table
            and x["table"]["family"] == "ip6"
            for x in tables
        )
        desired = sorted((r["mark"], r["address"]) for r in rows)

        def signature():
            observed = json.loads(
                command(["nft", "-j", "list", "table", "ip6", self.table])
            )
            data = json.dumps([desired, self.dev, observed], sort_keys=True)
            return hashlib.sha256(data.encode()).hexdigest()

        if exists and desired and signature() == self.value("nat_signature"):
            return
        prefix = f"ip6 {self.table}"
        script = [f"delete table {prefix}"] if exists else []
        if rows:
            script += [
                f"add table {prefix}",
                f"add map {prefix} users {{ type mark : ipv6_addr; }}",
                f"add chain {prefix} post {{ type nat hook postrouting priority srcnat - 1; policy accept; }}",
            ]
            entries = ", ".join(f"{r['mark']} : {r['address']}" for r in rows)
            script += [
                f"add element {prefix} users {{ {entries} }}",
                f'add rule {prefix} post oifname "{self.dev}" snat to meta mark map @users',
            ]
        if script:
            command(["nft", "-f", "-"], "\n".join(script) + "\n")
            self.save("nat_signature", signature() if rows else None)

    def reconcile(self, force_refresh=False):
        base_path = self.state / "base.json"
        base = json.loads(base_path.read_text())
        epoch = (self.state / "control.sock").stat().st_ino
        enabled = self.value("enabled", False)
        users = []
        targets = {}
        if enabled:
            targets = self.value("targets")
            if (
                force_refresh
                or not targets
                or self.value("date") != date.today().isoformat()
            ):
                try:
                    targets = resolve_list(
                        json.loads((self.directory / "targets.json").read_text())
                    )
                except (ValueError, OSError) as exc:
                    if force_refresh or targets is None:
                        raise
                    print(
                        f"Retaining previous DNS list: {type(exc).__name__}",
                        file=sys.stderr,
                    )
                else:
                    self.save("targets", targets)
                    self.save("date", date.today().isoformat())
            emails = set()
            for tag in self.tags:
                if base["inbounds"].get(tag) is None:
                    raise ValueError(f"Configured inbound missing: {tag}")
                emails.update(
                    u["email"]
                    for u in self.api("inbounduser", "-tag=" + tag, reply=True).get(
                        "users", []
                    )
                    if u.get("email")
                )
            for email in sorted(emails):
                # Marzban's numeric database ID survives credential rotation and renaming.
                match = re.fullmatch(r"([1-9][0-9]*)\..+", email)
                if match:
                    users.append(dict(self.allocate(match[1]), email=email))
        final, outs = render(base, self.tags if enabled else [], users, targets)
        guard = self.state / "managed-inbounds.json"
        if enabled and (
            not guard.exists() or json.loads(guard.read_text()) != self.tags
        ):
            temp = guard.with_suffix(".tmp")
            temp.write_text(json.dumps(self.tags))
            temp.replace(guard)
        existing_out = {
            o["tag"]
            for o in self.api("lso", reply=True).get("outbounds", [])
            if o.get("tag", "").startswith("mz6-")
        }
        wanted = {o["tag"] for o in outs}
        current_rules = self.api("lsrules", reply=True).get("rules", [])
        actual = [(r.get("ruleTag", ""), r.get("tag", "")) for r in current_rules]
        expected = [(r.get("ruleTag", ""), r.get("outboundTag", "")) for r in final]
        # Do not overwrite routes installed by another controller.
        original = [
            (r.get("ruleTag", ""), r.get("outboundTag", ""))
            for r in base["routing"]["rules"]
        ]
        if [r for r in actual if not r[0].startswith("mz6-")] != original:
            raise RuntimeError("Live base rules differ from the last node start")
        ready = self.addresses()
        if enabled:
            self.provision(users)
            # Atomic nft transaction also repairs kernel state after a firewall reload.
            self.nat(users)
        for out in outs:
            if out["tag"] not in existing_out:
                self.api("ado", data={"outbounds": [out]})
        if actual != expected:
            self.api("adrules", data={"routing": dict(base["routing"], rules=final)})
            observed = self.api("lsrules", reply=True).get("rules", [])
            if [(r.get("ruleTag", ""), r.get("tag", "")) for r in observed] != expected:
                raise RuntimeError("Routing readback mismatch")
        for tag in sorted(existing_out - wanted):
            self.api("rmo", tag)
        if not enabled:
            self.nat([])
            guard.unlink(missing_ok=True)
        keep = {r["address"] for r in users}
        # Keep allocations in SQLite even when the switch is off.
        for row in self.db.execute("select address from owned"):
            addr = row[0]
            if addr in ready and addr not in keep and ready[addr]["prefixlen"] == 128:
                command(["ip", "-6", "addr", "del", addr + "/128", "dev", self.dev])
        applied = {
            "epoch": epoch,
            "pid": base["pid"],
            "enabled": enabled,
            "generation": self.value("generation", 0),
        }
        if applied != self.value("applied"):
            self.save("applied", applied)
        return {
            "enabled": enabled,
            "users": len(users),
            "rule_count": len(final) - len(original),
            "list_date": self.value("date"),
            "verified": True,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "action", choices=["on", "off", "sync", "refresh", "reset", "status"]
    )
    parser.add_argument("user_id", nargs="?", type=int)
    parser.add_argument("--expected-address", type=ipaddress.IPv6Address)
    args = parser.parse_args()
    os.umask(0o077)
    with (args.config.parent / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        inst = Instance(args.config)
        with contextlib.closing(inst.db):
            if inst.value("mark_prefix") is None:
                mark_prefix = json.loads(args.config.read_text())["mark_prefix"]
                if type(mark_prefix) is not int or not 1 <= mark_prefix <= 32767:
                    raise ValueError("mark_prefix must be between 1 and 32767")
                inst.save("mark_prefix", mark_prefix)
            if args.action == "status":
                base = inst.state / "base.json"
                sock = inst.state / "control.sock"
                applied = inst.value("applied", {})
                verified = (
                    base.exists()
                    and sock.exists()
                    and applied.get("epoch") == sock.stat().st_ino
                    and applied.get("pid") == json.loads(base.read_text())["pid"]
                    and applied.get("enabled") == inst.value("enabled", False)
                    and applied.get("generation") == inst.value("generation", 0)
                )
                print(
                    json.dumps(
                        {
                            "enabled": inst.value("enabled", False),
                            "verified": verified,
                            "list_date": inst.value("date"),
                            "users": [
                                dict(r)
                                for r in inst.db.execute(
                                    "select identity,address from users order by cast(identity as integer)"
                                )
                            ],
                        }
                    )
                )
                return
            if args.action in ("on", "off"):
                inst.save("enabled", args.action == "on")
            if args.action == "reset":
                if not args.user_id or not args.expected_address:
                    raise ValueError(
                        "Reset requires the numeric user ID and current IPv6 address"
                    )
                row = inst.db.execute(
                    "select address from users where identity=?", (str(args.user_id),)
                ).fetchone()
                if not row or row[0] != str(args.expected_address):
                    raise ValueError(
                        "Allocation changed; refresh status before resetting"
                    )
                inst.save("generation", inst.value("generation", 0) + 1)
                inst.allocate(str(args.user_id), reset=True)
            print(json.dumps(inst.reconcile(force_refresh=args.action == "refresh")))


if __name__ == "__main__":
    main()
