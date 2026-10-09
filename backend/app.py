"""Read-only frontend API. No commands, arbitrary targets, or user PromQL."""

import asyncio
import json
import math
import os
import time
from contextlib import asynccontextmanager
from builtins import range as builtins_range
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query

PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
PROBE = os.getenv("PROBE_URL", "http://probe:8000")
RANGES = {"5m": 300, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
SERIES = {
    "rtt": ("network_ping_avg_ms", "ping"),
    "loss": ("network_packet_loss_percent", "ping"),
    "jitter": ("network_jitter_ms", "ping"),
    "tcp": ("network_tcp_connect_ms", "tcp"),
    "https": ("network_https_total_ms", "https"),
    "dns": ("network_dns_ms", "dns"),
    "tls": ("network_https_tls_ms", "https"),
    "mtr": ("network_mtr_avg_ms", "mtr"),
    "status": ("network_node_status", None),
}


@asynccontextmanager
async def lifespan(app):
    app.state.client = httpx.AsyncClient(
        timeout=8, limits=httpx.Limits(max_connections=24, max_keepalive_connections=12)
    )
    app.state.history_slots = asyncio.Semaphore(3)
    app.state.cache = {}
    yield
    await app.state.client.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


async def fetch(url, params=None):
    try:
        response = await app.state.client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Monitoring service unavailable") from exc


@app.get("/api/health")
async def health():
    probe, prom = await asyncio.gather(
        fetch(PROBE + "/health"),
        fetch(PROMETHEUS + "/api/v1/query", {"query": 'up{job="network-probe"}'}),
    )
    results = prom.get("data", {}).get("result", [])
    return {
        "ok": bool(probe.get("ok")),
        "prometheus": prom.get("status") == "success",
        "scraping": any(float(r["value"][1]) == 1 for r in results),
    }


@app.get("/api/nodes")
async def nodes():
    data = await fetch(PROBE + "/state")
    try:
        health = await fetch(PROMETHEUS + "/api/v1/query", {"query": 'up{job="network-probe"}'})
        data["prometheus_ok"] = any(
            float(r["value"][1]) == 1 for r in health.get("data", {}).get("result", [])
        )
    except HTTPException:
        data["prometheus_ok"] = False
    return data


@app.get("/api/routes")
async def routes():
    return await fetch(PROBE + "/routes")


@app.get("/api/events")
async def events(
    node: str | None = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, ge=1),
):
    params = {"limit": limit}
    if node:
        params["node"] = node
    if before:
        params["before"] = before
    return await fetch(PROBE + "/events", params)


@app.get("/api/history")
async def history(
    node: str = Query(..., max_length=64),
    range: Literal["5m", "1h", "6h", "24h", "7d", "30d"] = "1h",
    end: float | None = Query(None, ge=0),
):
    snapshot = await fetch(PROBE + "/state")
    match = next((n for n in snapshot["nodes"] if n["name"] == node), None)
    if not match:
        raise HTTPException(404, "Node not configured")
    if end is not None and (
        not math.isfinite(end) or end > time.time() + 30 or end < time.time() - RANGES["30d"]
    ):
        raise HTTPException(422, "End must be within the past 30 days")
    duration = RANGES[range]
    step = max(10, math.ceil(duration / 600))
    finish = math.floor((end or time.time()) / step) * step
    start = finish - duration
    cache_key = (node, match["host"], range, finish)
    cached = app.state.cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    labels = f'node={json.dumps(node)},host={json.dumps(match["host"])},job="network-probe"'

    async def query(key, metric, kind):
        expression = f'{metric}{{{labels}}} and on(job,instance) (up{{job="network-probe"}} == 1)'
        if kind:
            age = snapshot["settings"]["intervals"][kind] * 3
            expression += f' and on(node,region,host) (network_probe_timestamp_seconds{{{labels},kind="{kind}"}} > time()-{age})'
        data = await fetch(
            PROMETHEUS + "/api/v1/query_range",
            {"query": expression, "start": start, "end": finish, "step": step},
        )
        if data.get("status") != "success":
            raise HTTPException(503, "History query failed")
        output = []
        for item in data.get("data", {}).get("result", []):
            values = {
                int(float(ts)): float(v) if math.isfinite(float(v)) else None
                for ts, v in item["values"]
            }
            output.append(
                {
                    "label": item["metric"].get("port", key),
                    "points": [
                        [ts, values.get(ts)]
                        for ts in builtins_range(int(start), int(finish) + 1, step)
                    ],
                }
            )
        return key, output

    async with app.state.history_slots:
        result = dict(await asyncio.gather(*(query(key, *value) for key, value in SERIES.items())))
    payload = {"start": start, "end": finish, "step": step, "series": result}
    now = time.monotonic()
    app.state.cache = {k: v for k, v in app.state.cache.items() if v[0] > now}
    if len(app.state.cache) >= 64:
        app.state.cache.pop(next(iter(app.state.cache)))
    app.state.cache[cache_key] = (now + 10, payload)
    return payload
