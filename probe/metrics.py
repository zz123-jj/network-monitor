import time
from prometheus_client.core import GaugeMetricFamily
from probe.state import fresh, status

METRICS = {
    "ping": [
        "ping_rtt_ms",
        "ping_avg_ms",
        "ping_min_ms",
        "ping_max_ms",
        "packet_loss_percent",
        "jitter_ms",
    ],
    "dns": ["dns_ms"],
    "https": [
        "https_dns_ms",
        "https_connect_ms",
        "https_tls_ms",
        "https_ttfb_ms",
        "https_total_ms",
        "https_status_code",
    ],
    "mtr": [
        "mtr_avg_ms",
        "mtr_best_ms",
        "mtr_worst_ms",
        "mtr_loss_percent",
        "mtr_jitter_ms",
        "mtr_hops",
    ],
}


class Collector:
    def __init__(self, engine):
        self.engine = engine

    def collect(self):
        e, now = self.engine, time.time()
        families = {}

        def add(key, labels, value, extra_names=(), extra_values=()):
            if key not in families:
                families[key] = GaugeMetricFamily(
                    "network_" + key,
                    key.replace("_", " "),
                    labels=["node", "region", "host", *extra_names],
                )
            families[key].add_metric(
                [*labels, *extra_values], float("nan") if value is None else value
            )

        # No await here: state access remains within the single event-loop thread.
        for node in e.config.nodes:
            if not node.enabled:
                continue
            labels = [node.name, node.region, node.host]
            samples = e.samples.get(node.name, {})
            state = status(node, samples, e.config.settings, now)
            add(
                "node_up",
                labels,
                None if state in ("pending", "unknown") else int(state != "offline"),
            )
            add("node_status", labels, {"offline": 0, "warning": 1, "online": 2}.get(state))
            add("last_success_timestamp_seconds", labels, e.last_success.get(node.name))
            for kind, result in samples.items():
                valid = fresh(result, getattr(e.config.settings.intervals, kind), now)
                add("probe_timestamp_seconds", labels, result["timestamp"], ["kind"], [kind])
                add(
                    "probe_success",
                    labels,
                    int(result["success"]) if valid else None,
                    ["kind"],
                    [kind],
                )
                if kind == "tcp":
                    for port in node.tcp_ports:
                        item = next((p for p in result.get("ports", []) if p["port"] == port), {})
                        add(
                            "tcp_connect_ms",
                            labels,
                            item.get("tcp_connect_ms") if valid else None,
                            ["port"],
                            [str(port)],
                        )
                        add(
                            "tcp_success",
                            labels,
                            int(item.get("success", False)) if valid else None,
                            ["port"],
                            [str(port)],
                        )
                else:
                    for metric in METRICS[kind]:
                        add(metric, labels, result.get(metric) if valid else None)
        yield from families.values()
        for name, value in (
            ("config_ok", int(e.config_error is None)),
            ("scheduler_timestamp_seconds", e.heartbeat),
        ):
            metric = GaugeMetricFamily("network_" + name, name)
            metric.add_metric([], value)
            yield metric
