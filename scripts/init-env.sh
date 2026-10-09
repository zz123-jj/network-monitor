#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then cp .env.example .env; fi
if grep -q '^GRAFANA_ADMIN_PASSWORD=$' .env; then
  password=$(openssl rand -hex 24)
  sed -i.bak "s/^GRAFANA_ADMIN_PASSWORD=$/GRAFANA_ADMIN_PASSWORD=$password/" .env
  rm -f .env.bak
fi
chmod 600 .env
printf '环境已初始化。Grafana 密码保存在 .env。\n'
