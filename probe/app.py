import asyncio
import hashlib
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from prometheus_client import CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from common.config import load_config
from probe.checks import CHECKS
from probe.metrics import Collector
from probe.state import Store, fresh, status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("probe")
CONFIG_PATH = os.getenv("NODES_CONFIG", "/config/nodes.yaml")


class Engine:
    def __init__(self):
        self.config = load_config(CONFIG_PATH)  # invalid initial config fails startup visibly
        self.config_error = None
        self.fingerprint = None
        self.samples, self.last_success, self.tasks = {}, {}, {}
        self.heartbeat = time.time()
        self.store = Store(os.getenv("DB_PATH", "/data/monitor.sqlite3"))
        self.sem = asyncio.Semaphore(self.config.settings.concurrency)
        self.mtr_sem = asyncio.Semaphore(1)
        self.stop = asyncio.Event()

    def discovery(self):
        target_dir = Path(os.getenv("DISCOVERY_PATH", "/discovery"))
        target_dir.mkdir(parents=True, exist_ok=True)
        groups = {k: [] for k in ("icmp", "tcp", "http")}
        if self.config.settings.blackbox_enabled:
            for n in self.config.nodes:
                if not n.enabled:
                    continue
                labels = {"node": n.name, "region": n.region, "host": n.host}
                groups["icmp"].append({"targets": [n.host], "labels": labels})
                bracket_host = f"[{n.host}]" if ":" in n.host else n.host
                for port in n.tcp_ports:
                    groups["tcp"].append(
                        {
                            "targets": [f"{bracket_host}:{port}"],
                            "labels": {**labels, "port": str(port)},
                        }
                    )
                if n.https_url:
                    groups["http"].append({"targets": [n.https_url], "labels": labels})
        for kind, targets in groups.items():
            tmp = target_dir / f"{kind}.tmp"
            tmp.write_text(json.dumps(targets))
            os.chmod(tmp, 0o644)
            tmp.replace(target_dir / f"{kind}.json")

    async def run_check(self, node, kind):
        await asyncio.sleep(
            random.uniform(0, min(5, getattr(self.config.settings.intervals, kind)))
        )
        while not self.stop.is_set():
            started = time.monotonic()
            settings = self.config.settings
            try:
                async with self.mtr_sem if kind == "mtr" else self.sem:
                    result = await CHECKS[kind](node, settings)
                result["timestamp"] = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("probe failure node=%s kind=%s: %s", node.name, kind, str(exc)[:300])
                result = {"success": False, "timestamp": time.time(), "error": str(exc)[:300]}
            self.samples.setdefault(node.name, {})[kind] = result
            if result["success"] and kind in ("ping", "tcp", "https"):
                self.last_success[node.name] = result["timestamp"]
            if kind == "mtr":
                self.store.route(node.name, result)
            if kind == "ping":
                self.store.observe(node, self.samples[node.name], settings)
            elapsed = time.monotonic() - started
            interval = getattr(settings.intervals, kind)
            # At least 1s rest after overloaded/timeout probes. No overlapping check.
            await asyncio.sleep(max(1, interval - elapsed) + random.uniform(0, interval * 0.03))

    async def reconcile(self):
        data = Path(CONFIG_PATH).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest == self.fingerprint:
            self.config_error = None
            return
        config = load_config(CONFIG_PATH)
        # Cancel and await old tasks before replacing semaphore/config: no duplicate probes.
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        previous = {n.name: n for n in self.config.nodes}
        self.config = config
        self.sem = asyncio.Semaphore(config.settings.concurrency)
        self.tasks = {}
        active = {n.name for n in config.nodes if n.enabled}
        self.samples = {n: v for n, v in self.samples.items() if n in active}
        self.last_success = {n: v for n, v in self.last_success.items() if n in active}
        for node in config.nodes:
            if not node.enabled:
                continue
            old = previous.get(node.name)
            if old is None or (old.host, old.tcp_ports, old.https_url, old.enabled) != (
                node.host,
                node.tcp_ports,
                node.https_url,
                node.enabled,
            ):
                self.samples.pop(node.name, None)
                self.last_success.pop(node.name, None)
                self.store.db.execute("DELETE FROM routes WHERE node=?", (node.name,))
                self.store.db.execute("DELETE FROM alerts WHERE node=?", (node.name,))
                self.store.alerts = {
                    k: v for k, v in self.store.alerts.items() if k[0] != node.name
                }
            kinds = (
                ["ping", "dns"]
                + (["tcp"] if node.tcp_ports else [])
                + (["https"] if node.https_url else [])
                + (["mtr"] if config.settings.mtr_enabled else [])
            )
            if not config.settings.mtr_enabled:
                self.samples.get(node.name, {}).pop("mtr", None)
            for kind in kinds:
                self.tasks[(node.name, kind)] = asyncio.create_task(self.run_check(node, kind))
        self.discovery()
        self.store.prune(config.settings, active)
        self.fingerprint = digest
        self.config_error = None
        log.info("configuration loaded: %d enabled nodes", len(active))

    async def supervise(self):
        last_prune = 0
        while not self.stop.is_set():
            self.heartbeat = time.time()
            try:
                await self.reconcile()
                for key, task in list(self.tasks.items()):
                    if task.done():
                        error = task.exception() if not task.cancelled() else None
                        log.error("restarting stopped probe %s: %s", key, error)
                        node = next(n for n in self.config.nodes if n.name == key[0])
                        self.tasks[key] = asyncio.create_task(self.run_check(node, key[1]))
                if time.time() - last_prune > 3600:
                    self.store.prune(
                        self.config.settings, [n.name for n in self.config.nodes if n.enabled]
                    )
                    last_prune = time.time()
            except Exception as exc:
                self.config_error = str(exc)[:500]
                log.error("configuration/supervision error: %s", self.config_error)
            await asyncio.sleep(10)

    def snapshot(self):
        now = time.time()
        nodes = []
        for n in self.config.nodes:
            samples = self.samples.get(n.name, {})
            # stale values become null; timestamps and errors remain inspectable.
            checks = {}
            for kind, result in samples.items():
                valid = fresh(result, getattr(self.config.settings.intervals, kind), now)
                checks[kind] = {
                    **{k: v for k, v in result.items() if k != "hops"},
                    "stale": not valid,
                }
                if not valid:
                    for key in checks[kind]:
                        if key not in ("timestamp", "error", "stale"):
                            checks[kind][key] = None
            nodes.append(
                {
                    **n.model_dump(),
                    "status": status(n, samples, self.config.settings, now),
                    "checks": checks,
                    "last_success": self.last_success.get(n.name),
                }
            )
        return {
            "nodes": nodes,
            "server_time": now,
            "config_ok": self.config_error is None,
            "config_error": self.config_error,
            "settings": self.config.settings.model_dump(),
        }


@asynccontextmanager
async def lifespan(app):
    engine = Engine()
    app.state.engine = engine
    registry = CollectorRegistry()
    registry.register(Collector(engine))
    app.state.registry = registry
    await engine.reconcile()
    supervisor = asyncio.create_task(engine.supervise())
    yield
    engine.stop.set()
    supervisor.cancel()
    for task in engine.tasks.values():
        task.cancel()
    await asyncio.gather(supervisor, *engine.tasks.values(), return_exceptions=True)
    engine.store.db.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    ok = time.time() - app.state.engine.heartbeat < 30
    return Response(
        content='{"ok":' + str(ok).lower() + "}",
        media_type="application/json",
        status_code=200 if ok else 503,
    )


@app.get("/metrics")
async def metrics():
    return Response(
        generate_latest(app.state.registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
    )


@app.get("/state")
async def state():
    return app.state.engine.snapshot()


@app.get("/routes")
async def routes():
    return app.state.engine.store.routes()


@app.get("/events")
async def events(
    node: str | None = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, ge=1),
):
    return app.state.engine.store.events(node, limit, before)
