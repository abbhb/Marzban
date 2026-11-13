#!/usr/bin/python3
"""Forced-command SSH entry. One key is bound to exactly one instance."""

import ipaddress
import os
import re
import sys

instance = sys.argv[1]
if not re.fullmatch(r"[a-z0-9_]{1,20}", instance):
    sys.exit(1)
args = os.environ.get("SSH_ORIGINAL_COMMAND", "").split()
if len(args) == 3 and args[0] == "reset" and re.fullmatch(r"[1-9][0-9]*", args[1]):
    args = ["reset", args[1], "--expected-address", str(ipaddress.IPv6Address(args[2]))]
elif args not in (["status"], ["on"], ["off"], ["refresh"]):
    sys.exit(1)
os.execv(
    "/usr/bin/python3",
    [
        "python3",
        "/usr/local/lib/marzban-egress/manage.py",
        "--config",
        f"/etc/marzban-egress/{instance}/node.json",
        *args,
    ],
)
