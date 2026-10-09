#!/usr/bin/env python3
"""Offline structural checks; promtool does the authoritative Prometheus validation."""

import json
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.config import load_config

config = load_config(ROOT / "config/nodes.yaml")
for path in [*ROOT.glob("config/*.yml"), *ROOT.glob("grafana/provisioning/**/*.yml")]:
    assert isinstance(yaml.safe_load(path.read_text()), dict), path
board = json.loads((ROOT / "grafana/dashboards/network-monitor.json").read_text())
assert board["uid"] == "network-monitor" and len(board["panels"]) >= 12
for panel in board["panels"]:
    assert panel["datasource"]["uid"] == "prometheus"
    assert panel["targets"]
data = yaml.safe_load((ROOT / "grafana/provisioning/datasources/prometheus.yml").read_text())
assert data["datasources"][0]["url"] == "http://prometheus:9090"
compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
assert set(compose["services"]) == {
    "probe",
    "blackbox",
    "prometheus",
    "grafana",
    "backend",
    "frontend",
}
for name, service in compose["services"].items():
    assert service["restart"] == "unless-stopped"
    if name not in ("frontend", "grafana"):
        assert "ports" not in service
assert not compose["networks"]["monitoring_internal"].get("internal", False)
print(f"配置、Grafana provisioning、Compose 安全边界检查通过；{len(config.nodes)} 个配置节点。")
