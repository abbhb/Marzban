#!/usr/bin/env python3
"""Build Marzban's offline China CIDR snapshot from APNIC delegated stats.

The APNIC ``cc`` field records the economy of the organization receiving the
allocation.  It is useful for coarse source filtering, but it is not an
authoritative IP-geolocation database.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_SOURCE_URL = (
    "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "app" / "data"
INCLUDED_STATUSES = frozenset({"allocated", "assigned"})
NOTICE = (
    "APNIC cc=CN represents the allocation organization's economy; "
    "it does not necessarily equal the IP address's current physical location."
)


class DelegatedStatsError(ValueError):
    """Raised when the delegated statistics input is malformed or incomplete."""


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "marzban-mgma-cn-cidr-updater/1.0",
            "Accept": "text/plain",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _parse_header(fields: Sequence[str]) -> dict[str, str | int]:
    if len(fields) < 7 or fields[0] not in {"2", "2.3"}:
        raise DelegatedStatsError("unsupported delegated stats header")
    try:
        record_count = int(fields[3])
    except ValueError as exc:
        raise DelegatedStatsError("invalid record count in delegated stats header") from exc
    return {
        "version": fields[0],
        "registry": fields[1],
        "serial": fields[2],
        "record_count": record_count,
        "start_date": fields[4],
        "end_date": fields[5],
        "utc_offset": fields[6],
    }


def _ipv4_networks(start: str, count_text: str) -> Iterable[ipaddress.IPv4Network]:
    try:
        first = ipaddress.IPv4Address(start)
        count = int(count_text)
        if count <= 0:
            raise ValueError("IPv4 address count must be positive")
        last = ipaddress.IPv4Address(int(first) + count - 1)
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise DelegatedStatsError(
            f"invalid IPv4 delegated record: start={start!r}, count={count_text!r}"
        ) from exc
    return ipaddress.summarize_address_range(first, last)


def _ipv6_network(start: str, prefix_text: str) -> ipaddress.IPv6Network:
    try:
        prefix = int(prefix_text)
        return ipaddress.IPv6Network(f"{start}/{prefix}", strict=True)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
        raise DelegatedStatsError(
            f"invalid IPv6 delegated record: start={start!r}, prefix={prefix_text!r}"
        ) from exc


def parse_delegated_stats(
    payload: bytes,
) -> tuple[
    dict[str, str | int],
    list[ipaddress.IPv4Network],
    list[ipaddress.IPv6Network],
    dict[str, int | str | None],
]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DelegatedStatsError("delegated stats input is not UTF-8 text") from exc

    header: dict[str, str | int] | None = None
    ipv4: list[ipaddress.IPv4Network] = []
    ipv6: list[ipaddress.IPv6Network] = []
    status_counts: Counter[str] = Counter()
    source_record_count = 0
    latest_cn_record_date: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if header is None:
            header = _parse_header(fields)
            continue

        # Summary lines use '*' in the cc or type fields. Data records have the
        # fixed eight-column form defined by the RIR statistics exchange format.
        if len(fields) < 7 or fields[0] != "apnic":
            continue
        source_record_count += 1
        registry, cc, resource_type, start, value, record_date, status = fields[:7]
        del registry
        if cc.upper() != "CN" or status.lower() not in INCLUDED_STATUSES:
            continue
        status_counts[status.lower()] += 1
        if record_date and (latest_cn_record_date is None or record_date > latest_cn_record_date):
            latest_cn_record_date = record_date
        try:
            if resource_type == "ipv4":
                ipv4.extend(_ipv4_networks(start, value))
            elif resource_type == "ipv6":
                ipv6.append(_ipv6_network(start, value))
        except DelegatedStatsError as exc:
            raise DelegatedStatsError(f"line {line_number}: {exc}") from exc

    if header is None:
        raise DelegatedStatsError("delegated stats header was not found")
    if str(header["registry"]).lower() != "apnic":
        raise DelegatedStatsError(f"expected APNIC registry, got {header['registry']!r}")
    if not ipv4 or not ipv6:
        raise DelegatedStatsError("CN allocated/assigned IPv4 or IPv6 records are missing")

    details: dict[str, int | str | None] = {
        "parsed_source_records": source_record_count,
        "cn_allocated_records": status_counts["allocated"],
        "cn_assigned_records": status_counts["assigned"],
        "latest_cn_record_date": latest_cn_record_date,
    }
    return header, ipv4, ipv6, details


def _collapse_and_sort(
    networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    collapsed = ipaddress.collapse_addresses(networks)
    return sorted(collapsed, key=lambda network: (int(network.network_address), network.prefixlen))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def build_snapshot(
    payload: bytes,
    source_url: str,
    fetched_at: datetime,
    output_dir: Path,
) -> dict[str, object]:
    header, ipv4_input, ipv6_input, details = parse_delegated_stats(payload)
    ipv4 = _collapse_and_sort(ipv4_input)
    ipv6 = _collapse_and_sort(ipv6_input)
    cidr_bytes = ("\n".join(str(network) for network in (*ipv4, *ipv6)) + "\n").encode()

    cidr_sha256 = hashlib.sha256(cidr_bytes).hexdigest()
    source_sha256 = hashlib.sha256(payload).hexdigest()
    metadata: dict[str, object] = {
        "format_version": 1,
        "source": {
            "url": source_url,
            "registry": header["registry"],
            "format_version": header["version"],
            "serial": header["serial"],
            "declared_record_count": header["record_count"],
            "data_start_date": header["start_date"],
            "data_end_date": header["end_date"],
            "utc_offset": header["utc_offset"],
            "fetched_at": fetched_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sha256": source_sha256,
        },
        "selection": {
            "country_code": "CN",
            "statuses": sorted(INCLUDED_STATUSES),
        },
        "records": {
            **details,
            "ipv4_cidrs_before_collapse": len(ipv4_input),
            "ipv6_cidrs_before_collapse": len(ipv6_input),
            "ipv4_cidrs": len(ipv4),
            "ipv6_cidrs": len(ipv6),
            "cidrs": len(ipv4) + len(ipv6),
        },
        "output": {
            "file": "cn.cidr",
            "sha256": cidr_sha256,
        },
        "notice": NOTICE,
    }
    metadata_bytes = (
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()

    _atomic_write(output_dir / "cn.cidr", cidr_bytes)
    _atomic_write(output_dir / "cn-cidr-metadata.json", metadata_bytes)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--input",
        type=Path,
        help="read a previously downloaded delegated stats file instead of using the network",
    )
    source_group.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help=f"delegated stats URL (default: {DEFAULT_SOURCE_URL})",
    )
    parser.add_argument(
        "--metadata-source-url",
        default=DEFAULT_SOURCE_URL,
        help="source URL recorded when --input is used",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    fetched_at = datetime.now(timezone.utc)
    if args.input:
        payload = args.input.read_bytes()
        source_url = args.metadata_source_url
    else:
        payload = _download(args.source_url, args.timeout)
        source_url = args.source_url

    metadata = build_snapshot(payload, source_url, fetched_at, args.output_dir)
    records = metadata["records"]
    output = metadata["output"]
    print(
        "generated "
        f"{records['cidrs']} CIDRs "
        f"(IPv4 {records['ipv4_cidrs']}, IPv6 {records['ipv6_cidrs']}), "
        f"sha256={output['sha256']}"
    )


if __name__ == "__main__":
    main()
