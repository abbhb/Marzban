#!/usr/bin/env python3
"""Add a read-only socket observer to an explicit, pinned Xray checkout.

Builds an artifact only. Never installs it or restarts a local/remote service.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ORIGINAL = "func DialSystem(ctx context.Context, dest net.Destination, sockopt *SocketConfig) (net.Conn, error) {"
REPLACEMENT = ORIGINAL.replace("DialSystem(", "marzbanOriginalDialSystem(")


def patch(source):
    dialer = source / "transport/internet/dialer.go"
    observer = source / "transport/internet/marzban_observer.go"
    value = dialer.read_text()
    if REPLACEMENT in value and ORIGINAL not in value:
        pass
    elif value.count(ORIGINAL) == 1 and REPLACEMENT not in value:
        dialer.write_text(value.replace(ORIGINAL, REPLACEMENT))
    else:
        raise ValueError("Unrecognized Xray DialSystem signature; review this version before patching")
    shutil.copyfile(Path(__file__).with_name("observer.go"), observer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / "go.mod").is_file():
        parser.error("--source must be an Xray source checkout at a reviewed tag/commit")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    print("Building observer from Xray commit " + revision, flush=True)
    patch(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["go", "build", "-trimpath", "-o", str(args.output.resolve()), "./main"], cwd=source, check=True)
    manifest = {
        "xray_commit": revision,
        "observer_sha256": hashlib.sha256(Path(__file__).with_name("observer.go").read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        **json.loads(subprocess.check_output(["go", "env", "-json", "GOOS", "GOARCH", "GOVERSION"], cwd=source, text=True)),
    }
    args.output.with_name(args.output.name + ".json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
