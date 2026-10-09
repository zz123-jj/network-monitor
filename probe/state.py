"""Freshness-aware state and persisted transition events."""

import json
import sqlite3
import time
from pathlib import Path


def fresh(result, interval, now=None):
    return bool(result) and (now or time.time()) - result["timestamp"] <= interval * 3


def status(node, samples, settings, now=None):
    if not node.enabled:
        return "disabled"
    required = (
        ["ping"] + (["tcp"] if node.tcp_ports else []) + (["https"] if node.https_url else [])
    )
    if any(not samples.get(k) for k in required):
        return "pending"
    if any(not fresh(samples[k], getattr(settings.intervals, k), now) for k in required):
        return "unknown"
    if any(samples[k].get("error") for k in required):
        return (
            "unknown"  # local tool/config errors are not evidence that the remote node is offline
        )
    if not any(samples[k].get("reachable", samples[k]["success"]) for k in required):
        return "offline"
    ping = samples["ping"]
    t = settings.thresholds
    failed_port = any(not p["success"] for p in samples.get("tcp", {}).get("ports", []))
    warn = (
        not all(samples[k]["success"] for k in required)
        or failed_port
        or (ping.get("ping_avg_ms") or 0) >= t.warning_rtt_ms
        or (ping.get("packet_loss_percent") or 0) >= t.warning_loss_percent
        and (ping.get("packet_loss_percent") or 0) > 0
        or (ping.get("jitter_ms") or 0) >= t.warning_jitter_ms
    )
    return "warning" if warn else "online"


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, node TEXT NOT NULL,
          type TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_time ON events(timestamp DESC);
        CREATE INDEX IF NOT EXISTS events_node ON events(node, timestamp DESC);
        CREATE TABLE IF NOT EXISTS alerts(node TEXT, type TEXT, data TEXT NOT NULL, PRIMARY KEY(node,type));
        CREATE TABLE IF NOT EXISTS routes(node TEXT PRIMARY KEY, data TEXT NOT NULL);
        """)
        self.alerts = {
            (n, k): json.loads(data)
            for n, k, data in self.db.execute("SELECT node,type,data FROM alerts")
        }
        self.db.commit()

    def route(self, node, result):
        self.db.execute(
            "INSERT OR REPLACE INTO routes VALUES (?,?)",
            (node, json.dumps(result, allow_nan=False)),
        )
        self.db.commit()

    def routes(self):
        return {n: json.loads(data) for n, data in self.db.execute("SELECT node,data FROM routes")}

    def event(self, node, kind, severity, message, now):
        self.db.execute(
            "INSERT INTO events(timestamp,node,type,severity,message) VALUES(?,?,?,?,?)",
            (now, node, kind, severity, message),
        )

    def transition(self, node, kind, active, severity, message, settings, now):
        key = (node, kind)
        state = self.alerts.setdefault(
            key, {"active": False, "candidate": None, "count": 0, "last_event": 0}
        )
        if state["candidate"] == active:
            state["count"] = min(state["count"] + 1, settings.thresholds.debounce_samples)
        else:
            state["candidate"], state["count"] = active, 1
        if state["active"] != active and state["count"] >= settings.thresholds.debounce_samples:
            state["active"] = active
            # Recovery is always recorded. Cooldown only suppresses re-entry noise.
            if not active or now - state["last_event"] >= settings.thresholds.cooldown_seconds:
                self.event(
                    node,
                    kind if active else "recovery",
                    severity if active else "info",
                    message if active else f"{kind} recovered",
                    now,
                )
                if active:
                    state["last_event"] = now
        self.db.execute(
            "INSERT OR REPLACE INTO alerts VALUES (?,?,?)", (node, kind, json.dumps(state))
        )

    def observe(self, node, samples, settings):
        now = time.time()
        value = status(node, samples, settings, now)
        if value in ("pending", "unknown", "disabled"):
            return
        p = samples["ping"]
        self.transition(
            node.name,
            "offline",
            value == "offline",
            "critical",
            "Node offline: all configured reachability checks failed",
            settings,
            now,
        )
        for kind, metric, unit, key in (
            ("high_latency", "ping_avg_ms", "ms", "rtt_ms"),
            ("packet_loss", "packet_loss_percent", "%", "loss_percent"),
            ("high_jitter", "jitter_ms", "ms", "jitter_ms"),
        ):
            number = p.get(metric)
            if number is None:
                continue  # missing data must not clear an existing anomaly
            warn, critical = (
                getattr(settings.thresholds, "warning_" + key),
                getattr(settings.thresholds, "critical_" + key),
            )
            self.transition(
                node.name,
                kind,
                number >= warn and number > 0,
                "critical" if number >= critical else "warning",
                f"{kind}: {number:.1f}{unit} (warning ≥ {warn:g}{unit})",
                settings,
                now,
            )
        self.db.commit()

    def events(self, node=None, limit=100, before=None):
        clauses, args = [], []
        if node:
            clauses.append("node=?")
            args.append(node)
        if before:
            clauses.append("id<?")
            args.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute(
            "SELECT id,timestamp,node,type,severity,message FROM events"
            + where
            + " ORDER BY id DESC LIMIT ?",
            [*args, limit],
        ).fetchall()
        return [
            dict(zip(("id", "timestamp", "node", "type", "severity", "message"), row))
            for row in rows
        ]

    def prune(self, settings, active_names):
        self.db.execute(
            "DELETE FROM events WHERE timestamp < ?",
            (time.time() - settings.event_retention_days * 86400,),
        )
        self.db.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (settings.event_max_rows,),
        )
        for (name,) in self.db.execute("SELECT node FROM routes").fetchall():
            if name not in active_names:
                self.db.execute("DELETE FROM routes WHERE node=?", (name,))
        for name in {key[0] for key in self.alerts} - set(active_names):
            self.db.execute("DELETE FROM alerts WHERE node=?", (name,))
            self.alerts = {key: val for key, val in self.alerts.items() if key[0] != name}
        self.db.commit()
