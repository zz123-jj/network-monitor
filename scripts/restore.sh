#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $# == 1 ]] || { echo '用法：bash scripts/restore.sh backups/network-monitor-日期.tar.gz'; exit 1; }
archive=$(realpath "$1")
[[ -f "$archive" ]] || exit 1
# Never overwrite live data. Restore onto newly created empty data volumes.
for service in probe prometheus grafana; do
  [[ -z "$(docker compose ps -q --status running "$service")" ]] || { echo '请先 docker compose down（不要使用 -v）'; exit 1; }
done
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
# Archive must be a trusted backup produced by backup.sh.
tar -xzf "$archive" -C "$staging"
for service in probe prometheus grafana; do [[ -f "$staging/$service.tar" ]] || exit 1; done
docker compose create probe prometheus grafana >/dev/null
for service in probe prometheus grafana; do
  cid=$(docker compose ps -aq "$service")
  destination=/data
  [[ "$service" == prometheus ]] && destination=/prometheus
  [[ "$service" == grafana ]] && destination=/var/lib/grafana
  volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Destination .Name}}{{end}}{{end}}' "$cid" | awk -v dest="$destination" '$1==dest{print $2}')
  docker compose run --rm --no-deps --user 0 --entrypoint python -v "$volume:/restore-data" probe -c 'from pathlib import Path; assert not any(Path("/restore-data").iterdir()), "目标数据卷非空：请换新 COMPOSE_PROJECT_NAME 恢复，防止覆盖现有历史"'
  docker compose run --rm --no-deps -T --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --entrypoint tar -v "$volume:/restore-data" probe -C /restore-data -xpf - < "$staging/$service.tar"
done
printf '数据已恢复。请核对备份里的 config/grafana/.env 与本机配置，按 README 手动还原后 docker compose up -d。\n'
