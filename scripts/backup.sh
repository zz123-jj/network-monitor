#!/usr/bin/env bash
# Consistent cold backup. Short downtime, no loss of TSDB/WAL integrity.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
archive="backups/network-monitor-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
staging=$(mktemp -d)
cleanup() { rm -rf "$staging"; docker compose start probe prometheus grafana >/dev/null || true; }
trap cleanup EXIT
# Resolve actual mounted named volumes rather than assuming a project name.
for service in probe prometheus grafana; do
  cid=$(docker compose ps -q "$service")
  [[ -n "$cid" ]] || { echo "服务 $service 未运行，无法自动确定数据卷"; exit 1; }
  destination=/data
  [[ "$service" == prometheus ]] && destination=/prometheus
  [[ "$service" == grafana ]] && destination=/var/lib/grafana
  docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Destination .Name}}{{end}}{{end}}' "$cid" | awk -v dest="$destination" '$1==dest{print $2}' > "$staging/$service.volume"
  [[ -s "$staging/$service.volume" ]] || exit 1
done
docker compose stop probe prometheus grafana
for service in probe prometheus grafana; do
  volume=$(cat "$staging/$service.volume")
  docker compose run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --entrypoint tar -v "$volume:/backup-data:ro" probe -C /backup-data -cpf - . > "$staging/$service.tar"
done
cp -R config grafana "$staging/"
cp .env docker-compose.yml "$staging/"
# .env contains credentials. Keep archive private.
tar -czf "$archive" -C "$staging" .
chmod 600 "$archive"
printf '备份完成：%s（含密码，请安全保存）\n' "$archive"
