#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
archive_dir="${1:-../network-monitor-offline}"
archive_dir=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$archive_dir")
if command -v sha256sum >/dev/null; then hash_command=(sha256sum); else hash_command=(shasum -a 256); fi
[[ -f .env ]] || { echo 'Create .env first: cp .env.example .env && bash scripts/init-env.sh'; exit 1; }
[[ ! -f "$archive_dir/network-monitor-runtime.tar.gz.tmp" && ! -f "$archive_dir/network-monitor-project.tar.gz.tmp" ]] || { echo 'Export is incomplete; finish or rerun export before deployment.'; exit 1; }
architecture=$(docker info --format '{{.Architecture}}')
case "$architecture" in x86_64) architecture=amd64;; aarch64) architecture=arm64;; esac
[[ "$architecture" == "$(cat "$archive_dir/architecture.txt")" ]] || { echo 'Archive architecture does not match this Docker host.'; exit 1; }
project_name=$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
[[ "$project_name" == "$(cat "$archive_dir/project-name.txt")" ]] || { echo 'Use the original COMPOSE_PROJECT_NAME and image names for this archive.'; exit 1; }
(cd "$archive_dir" && "${hash_command[@]}" -c network-monitor-runtime.tar.gz.sha256)
docker load -i "$archive_dir/network-monitor-runtime.tar.gz"
docker compose config --quiet
docker compose up -d --no-build --pull never --wait --wait-timeout 180
docker compose ps
