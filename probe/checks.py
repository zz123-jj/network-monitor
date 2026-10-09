"""Bounded probes. Argument arrays only; no shell, no request-supplied targets."""

import asyncio
import ipaddress
import json
import os
import re
import socket
import statistics
import time
from urllib.parse import urlsplit


async def command(args: list[str], timeout: float) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def family(host):
    try:
        return socket.AF_INET6 if ipaddress.ip_address(host).version == 6 else socket.AF_INET
    except ValueError:
        return socket.AF_INET


def parse_ping(output):
    samples = [float(x) for x in re.findall(r"time[=<]([\d.]+)\s*ms", output)]
    summary = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", output)
    if not summary:
        raise ValueError("ping missing packet summary")
    sent, received = map(int, summary.groups())
    values = {
        "success": received > 0,
        "packet_loss_percent": 100 * (sent - received) / max(1, sent),
        "ping_rtt_ms": samples[-1] if samples else None,
        "ping_avg_ms": statistics.mean(samples) if samples else None,
        "ping_min_ms": min(samples) if samples else None,
        "ping_max_ms": max(samples) if samples else None,
        # Mean absolute successive RTT difference; no loss treated as RTT=0.
        "jitter_ms": statistics.mean(abs(a - b) for a, b in zip(samples, samples[1:]))
        if len(samples) > 1
        else None,
    }
    return values


async def ping(node, settings):
    version = "-6" if family(node.host) == socket.AF_INET6 else "-4"
    code, out, err = await command(
        [
            "ping",
            version,
            "-n",
            "-c",
            str(settings.ping_count),
            "-i",
            "0.2",
            "-W",
            "2",
            "-w",
            "6",
            node.host,
        ],
        8,
    )
    if code not in (0, 1):
        raise RuntimeError(err[:200] or "ping process failed")
    return parse_ping(out)


async def tcp(node, settings):
    async def one(port):
        begin = time.perf_counter()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(node.host, port, family=family(node.host)), 5
            )
            elapsed = (time.perf_counter() - begin) * 1000
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), 1)
            return {"port": port, "success": True, "tcp_connect_ms": elapsed}
        except (OSError, asyncio.TimeoutError):
            return {"port": port, "success": False, "tcp_connect_ms": None}

    results = []
    # Sequential per node keeps total global socket concurrency bounded.
    for port in node.tcp_ports:
        results.append(await one(port))
    return {"success": any(x["success"] for x in results), "ports": results}


async def dns(node, settings):
    begin = time.perf_counter()
    code, output, _ = await command(
        ["getent", "ahostsv6" if family(node.host) == socket.AF_INET6 else "ahostsv4", node.host], 5
    )
    return {
        "success": code == 0 and bool(output.strip()),
        "dns_ms": (time.perf_counter() - begin) * 1000 if code == 0 and output.strip() else None,
    }


def parse_curl(data, code):
    t = {
        key: float(data.get(key, 0))
        for key in (
            "time_namelookup",
            "time_connect",
            "time_appconnect",
            "time_starttransfer",
            "time_total",
        )
    }
    status = int(data.get("http_code", 0))
    success = code == 0 and 200 <= status < 400
    # curl timings are cumulative. Connect/TLS are stage durations; TTFB is cumulative.
    return {
        "success": success,
        "reachable": success or status > 0 or t["time_connect"] > 0,
        "https_status_code": status,
        "https_dns_ms": t["time_namelookup"] * 1000 if code == 0 else None,
        "https_connect_ms": max(0, t["time_connect"] - t["time_namelookup"]) * 1000
        if code == 0
        else None,
        "https_tls_ms": max(0, t["time_appconnect"] - t["time_connect"]) * 1000
        if code == 0 and t["time_appconnect"]
        else None,
        "https_ttfb_ms": t["time_starttransfer"] * 1000 if code == 0 else None,
        "https_total_ms": t["time_total"] * 1000 if code == 0 else None,
    }


async def https(node, settings):
    host = urlsplit(node.https_url).hostname
    code, out, _ = await command(
        [
            "curl",
            "--disable",
            "-6" if family(host) == socket.AF_INET6 else "-4",
            "--silent",
            "--show-error",
            "--globoff",
            "--head",
            "--output",
            "/dev/null",
            "--noproxy",
            "*",
            "--proto",
            "=http,https",
            "--connect-timeout",
            "5",
            "--max-time",
            "10",
            "--write-out",
            "%{json}",
            "--url",
            node.https_url,
        ],
        12,
    )
    return parse_curl(json.loads(out), code)


def parse_mtr(output, target):
    raw = json.loads(output)
    hubs = raw.get("report", {}).get("hubs", [])
    if not hubs:
        raise ValueError("empty MTR report")
    hops = []
    for index, hub in enumerate(hubs[:30]):
        host = str(hub.get("host", "???"))[:253]
        unknown = host in ("???", "*", "")

        def number(key):
            try:
                value = float(hub[key])
                return value if value == value and abs(value) != float("inf") else None
            except (KeyError, TypeError, ValueError):
                return None

        hops.append(
            {
                "hop": index + 1,
                "ip": None if unknown else host,
                "hostname": None,
                "avg_ms": None if unknown else number("Avg"),
                "best_ms": None if unknown else number("Best"),
                "worst_ms": None if unknown else number("Wrst"),
                "loss_percent": number("Loss%"),
                "jitter_ms": None if unknown else number("StDev"),
            }
        )
    last = hops[-1]
    # Only call this an end-to-end metric when the last hop is the resolved target.
    reached = (
        last["ip"] == target and last["avg_ms"] is not None and (last["loss_percent"] or 0) < 100
    )
    return {
        "success": reached,
        "hops": hops,
        "mtr_hops": len(hops),
        **{
            f"mtr_{dest}": last[src] if reached else None
            for dest, src in (
                ("avg_ms", "avg_ms"),
                ("best_ms", "best_ms"),
                ("worst_ms", "worst_ms"),
                ("loss_percent", "loss_percent"),
                ("jitter_ms", "jitter_ms"),
            )
        },
    }


async def mtr(node, settings):
    # Numeric output avoids reverse DNS traffic and unbounded resolver delays.
    loop = asyncio.get_running_loop()
    answers = await asyncio.wait_for(
        loop.getaddrinfo(node.host, None, family=family(node.host), type=socket.SOCK_STREAM), 5
    )
    target = answers[0][4][0]
    version = "-6" if family(target) == socket.AF_INET6 else "-4"
    code, out, err = await command(
        [
            "mtr",
            version,
            "--json",
            "--no-dns",
            "--report-cycles",
            "10",
            "--interval",
            "1",
            "--max-ttl",
            "30",
            target,
        ],
        45,
    )
    if code != 0:
        raise RuntimeError(err[:200] or "MTR failed")
    return parse_mtr(out, target)


CHECKS = {"ping": ping, "tcp": tcp, "https": https, "dns": dns, "mtr": mtr}
