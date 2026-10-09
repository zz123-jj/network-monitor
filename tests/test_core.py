import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError
from prometheus_client import CollectorRegistry, generate_latest
from common.config import Configuration, Node, Settings, load_config
from probe.checks import command, parse_curl, parse_mtr, parse_ping
from probe.metrics import Collector
from probe.state import Store, status


@pytest.mark.parametrize(
    "host", ["-c5", "1.2.3.4;touch /tmp/pwn", "a$(id)", "a`id`", "https://x", "a\nb", "a..com"]
)
def test_host_injection_rejected(host):
    with pytest.raises(ValidationError):
        Node(name="x", host=host)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://a:b@example.com",
        "https://example.com\r\nX:x",
        "https://example.com:99999",
    ],
)
def test_url_rejected(url):
    with pytest.raises(ValidationError):
        Node(name="x", host="127.0.0.1", https_url=url)


def test_config_bounded():
    with pytest.raises(ValidationError):
        Configuration(nodes=[Node(name="a", host="1.1.1.1")] * 2)
    with pytest.raises(ValidationError):
        Node(name="a", host="1.1.1.1", tcp_ports=[22, 22])
    with pytest.raises(ValidationError):
        Settings(intervals={"mtr": 10})
    config = load_config(Path(__file__).parents[1] / "config/nodes.yaml")
    assert config.settings.intervals.ping == 10


def sample(success=True, **kw):
    return {"success": success, "timestamp": time.time(), **kw}


def test_blocked_icmp_does_not_mean_offline():
    n = Node(name="a", host="1.1.1.1", tcp_ports=[443])
    p = {
        "ping": sample(False, packet_loss_percent=100),
        "tcp": sample(True, ports=[{"success": True}]),
    }
    assert status(n, p, Settings()) == "warning"
    p["tcp"] = sample(False, ports=[{"success": False}])
    assert status(n, p, Settings()) == "offline"
    p["ping"]["timestamp"] -= 100
    assert status(n, p, Settings()) == "unknown"
    p["ping"] = sample(False, error="permission denied")
    assert status(n, p, Settings()) == "unknown"


def test_ping_loss_jitter_and_missing():
    text = "64 bytes: time=10.0 ms\n64 bytes: time=14.0 ms\n5 packets transmitted, 2 received, 60% packet loss"
    result = parse_ping(text)
    assert result["packet_loss_percent"] == 60
    assert result["jitter_ms"] == 4
    assert result["ping_avg_ms"] == 12
    result = parse_ping("5 packets transmitted, 0 received, 100% packet loss")
    assert result["ping_avg_ms"] is None and not result["success"]
    with pytest.raises(ValueError):
        parse_ping("ping: permissions")


def test_curl_stage_timings():
    result = parse_curl(
        {
            "http_code": 200,
            "time_namelookup": 0.01,
            "time_connect": 0.04,
            "time_appconnect": 0.08,
            "time_starttransfer": 0.15,
            "time_total": 0.16,
        },
        0,
    )
    assert result["https_connect_ms"] == pytest.approx(30)
    assert result["https_tls_ms"] == pytest.approx(40)
    assert result["https_ttfb_ms"] == 150
    assert parse_curl({}, 28)["https_total_ms"] is None
    assert not parse_curl({"http_code": 503}, 0)["success"]


def test_mtr_requires_target_and_preserves_unknown_hop():
    hubs = [
        {"host": "???", "Loss%": 100, "Avg": 0},
        {"host": "1.1.1.1", "Loss%": 0, "Avg": 42, "Best": 40, "Wrst": 50, "StDev": 2},
    ]
    result = parse_mtr(json.dumps({"report": {"hubs": hubs}}), "1.1.1.1")
    assert result["success"] and result["mtr_avg_ms"] == 42
    assert result["hops"][0]["avg_ms"] is None
    result = parse_mtr(json.dumps({"report": {"hubs": hubs}}), "8.8.8.8")
    assert not result["success"] and result["mtr_avg_ms"] is None


def test_event_debounce_cooldown_and_restart(tmp_path):
    db = tmp_path / "x.sqlite3"
    store = Store(db)
    s = Settings()
    n = Node(name="Tokyo", host="1.1.1.1")
    p = {"ping": sample(False, packet_loss_percent=100)}
    store.observe(n, p, s)
    store.observe(n, p, s)
    assert store.events() == []
    store.observe(n, p, s)
    events = store.events()
    assert {e["type"] for e in events} == {"offline", "packet_loss"}
    store.db.close()
    store = Store(db)
    for _ in range(8):
        store.observe(n, p, s)
    assert len(store.events()) == len(events)
    p = {"ping": sample(True, ping_avg_ms=10, packet_loss_percent=0, jitter_ms=1)}
    for _ in range(3):
        store.observe(n, p, s)
    assert sum(e["type"] == "recovery" for e in store.events()) == 2
    store.db.close()


def test_metric_stale_not_zero_and_bounded_labels():
    class Engine:
        config = Configuration(nodes=[Node(name="Tokyo", host="1.1.1.1", region="Japan")])
        samples = {"Tokyo": {"ping": sample(True, ping_avg_ms=12, packet_loss_percent=0)}}
        last_success = {}
        heartbeat = time.time()
        config_error = None

    engine = Engine()
    registry = CollectorRegistry()
    registry.register(Collector(engine))
    text = generate_latest(registry).decode()
    assert 'network_ping_avg_ms{host="1.1.1.1",node="Tokyo",region="Japan"} 12.0' in text
    engine.samples["Tokyo"]["ping"]["timestamp"] -= 100
    text = generate_latest(registry).decode()
    assert 'network_ping_avg_ms{host="1.1.1.1",node="Tokyo",region="Japan"} NaN' in text
    engine.config = Configuration()
    assert 'node="Tokyo"' not in generate_latest(registry).decode()


def test_subprocess_timeout_kills_process(tmp_path):
    marker = tmp_path / "should-not-exist"

    async def check():
        with pytest.raises(asyncio.TimeoutError):
            await command(
                [
                    sys.executable,
                    "-c",
                    f'import time;time.sleep(.2);open({str(marker)!r},"w").write("bad")',
                ],
                0.03,
            )
        await asyncio.sleep(0.3)
        assert not marker.exists()

    asyncio.run(check())


def test_reverted_config_recovers_health_and_metadata_preserves_alert(tmp_path, monkeypatch):
    import probe.app as module

    config = tmp_path / "nodes.yaml"
    config.write_text("nodes: [{name: Tokyo, host: 127.0.0.1}]")
    monkeypatch.setattr(module, "CONFIG_PATH", str(config))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data.sqlite3"))
    monkeypatch.setenv("DISCOVERY_PATH", str(tmp_path / "discovery"))

    async def run():
        e = module.Engine()
        await e.reconcile()
        e.config_error = "previous invalid configuration"
        await e.reconcile()
        assert e.config_error is None
        e.store.alerts[("Tokyo", "high_latency")] = {"active": True}
        config.write_text("nodes: [{name: Tokyo, host: 127.0.0.1, description: metadata update}]")
        await e.reconcile()
        assert e.store.alerts[("Tokyo", "high_latency")]["active"]
        for task in e.tasks.values():
            task.cancel()
        await asyncio.gather(*e.tasks.values(), return_exceptions=True)
        e.store.db.close()

    asyncio.run(run())


def test_https_application_error_is_reachable_warning():
    n = Node(name="Tokyo", host="1.1.1.1", https_url="https://example.com/")
    http = parse_curl({"http_code": 503, "time_connect": 0.03}, 0)
    assert not http["success"] and http["reachable"]
    samples = {"ping": sample(False, packet_loss_percent=100), "https": sample(**http)}
    assert status(n, samples, Settings()) == "warning"
