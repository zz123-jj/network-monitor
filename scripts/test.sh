#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose config --quiet
# Build all app images so this also verifies npm ci + Vite build.
docker compose build
docker compose run --rm --no-deps --entrypoint python probe -c 'import ast,pathlib; [ast.parse(p.read_text()) for d in ("common","probe") for p in pathlib.Path(d).rglob("*.py")]; print("Probe Python syntax OK")'
docker compose run --rm --no-deps --entrypoint python backend -c 'import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path("backend").rglob("*.py")]; print("Backend Python syntax OK")'
docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/grafana:/app/grafana:ro" -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" -v "$PWD/config:/app/config:ro" --entrypoint python probe /app/scripts/validate.py
docker compose run --rm --no-deps --entrypoint /bin/promtool prometheus check config /etc/prometheus/prometheus.yml
docker compose up -d --wait --wait-timeout 180
# Execute checks within containers; internal ports are intentionally not published.
docker compose exec -T prometheus wget -qO- http://localhost:9090/-/healthy
docker compose exec -T probe python -c 'import urllib.request; r=urllib.request.urlopen("http://localhost:8000/metrics"); assert b"network_scheduler_timestamp_seconds" in r.read(); print("Probe metrics OK")'
docker compose exec -T blackbox wget -qO /dev/null http://localhost:9115/metrics
docker compose exec -T frontend wget -qO- http://127.0.0.1:8080/api/health
docker compose exec -T backend python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://prometheus:9090/api/v1/query?query=up")); assert any(x["metric"].get("job")=="network-probe" and x["value"][1]=="1" for x in d["data"]["result"]); print("Prometheus scrape OK")'
docker compose exec -T backend python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://grafana:3000/api/health")); assert d["database"]=="ok"; print("Grafana database OK")'
docker compose exec -T grafana sh -c '
  auth=$(printf "%s:%s" "$GF_SECURITY_ADMIN_USER" "$GF_SECURITY_ADMIN_PASSWORD" | base64 | tr -d "\n")
  wget -qO- --header "Authorization: Basic $auth" http://localhost:3000/api/datasources/uid/prometheus/health | grep -Eq '"'"'"status"[[:space:]]*:[[:space:]]*"OK"'"'"'
  wget -qO- --header "Authorization: Basic $auth" "http://localhost:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=up%7Bjob%3D%22network-probe%22%7D" | grep -q '"'"'"1"'"'"'
  echo "Grafana datasource and query OK"
'
docker compose ps
printf '\n全部配置/构建/服务健康检查通过。真实节点的 Ping/TCP/HTTPS/MTR 请继续按 README 验证。\n'
