#!/usr/bin/env bash
# Ubuntu 24.04, official Docker apt repository. Never changes firewall rules.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo '请使用 sudo bash scripts/install.sh'; exit 1; fi
. /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 ]]; then echo '本脚本仅适用于 Ubuntu 24.04'; exit 1; fi
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  systemctl enable --now docker
  echo 'Docker 与 Compose 已存在。'; exit 0
fi
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
    echo "检测到 $package，请按 Docker 官方迁移说明处理已有安装，脚本不自动删除。"; exit 1
  fi
done
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL --retry 3 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
architecture=$(dpkg --print-architecture)
cat > /etc/apt/sources.list.d/docker.sources <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version
docker compose version
