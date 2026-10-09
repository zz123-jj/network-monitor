#!/usr/bin/env bash
# Export verified local images and source; does not include application data volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
archive_dir="${1:-../network-monitor-offline}"
archive_dir=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$archive_dir")
if command -v sha256sum >/dev/null; then hash_command=(sha256sum); else hash_command=(shasum -a 256); fi
python3 - "$archive_dir" <<'PY'
import pathlib, sys
root = pathlib.Path.cwd().resolve()
dest = pathlib.Path(sys.argv[1])
if dest == root or root in dest.parents or dest in root.parents:
    raise SystemExit('Choose a dedicated export directory outside the project.')
PY
mkdir -p "$archive_dir"
chmod 700 "$archive_dir"
docker compose config --quiet
images=()
while IFS= read -r image; do images+=("$image"); done < <(docker compose config --images | sort -u)
[[ ${#images[@]} -gt 0 ]] || { echo 'No service images to export.'; exit 1; }
architecture=$(docker image inspect "${images[@]}" --format '{{.Architecture}}' | sort -u)
case "$architecture" in amd64|arm64) ;; *) echo 'All service images must use one supported architecture.'; exit 1;; esac
printf '%s\n' "$architecture" > "$archive_dir/architecture.txt"
docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' > "$archive_dir/project-name.txt"
docker image save "${images[@]}" | gzip -1 > "$archive_dir/network-monitor-runtime.tar.gz.tmp"
mv "$archive_dir/network-monitor-runtime.tar.gz.tmp" "$archive_dir/network-monitor-runtime.tar.gz"
(cd "$archive_dir" && "${hash_command[@]}" network-monitor-runtime.tar.gz > network-monitor-runtime.tar.gz.sha256)
docker image inspect "${images[@]}" --format '{{json .RepoTags}} {{.Id}} {{.Architecture}}' > "$archive_dir/runtime-images.txt"
python3 - "$archive_dir" <<'PY'
import pathlib, sys, tarfile
dest = pathlib.Path(sys.argv[1])
ignored = {'.git', 'node_modules', 'dist', '__pycache__', '.pytest_cache', '.ruff_cache', '.venv', 'backups', 'work'}
def include(member):
    path = pathlib.PurePosixPath(member.name)
    if ignored.intersection(path.parts):
        return None
    if path.name.startswith('.env') and path.name != '.env.example':
        return None
    if path.suffix == '.pyc' or '.sqlite3' in path.name:
        return None
    return member
with tarfile.open(dest/'network-monitor-project.tar.gz.tmp', 'w:gz') as archive:
    archive.add('.', arcname='.', filter=include)
(dest/'network-monitor-project.tar.gz.tmp').replace(dest/'network-monitor-project.tar.gz')
PY
(cd "$archive_dir" && "${hash_command[@]}" network-monitor-project.tar.gz > network-monitor-project.tar.gz.sha256)
chmod 600 "$archive_dir"/network-monitor-*.tar.gz* "$archive_dir"/architecture.txt "$archive_dir"/project-name.txt "$archive_dir"/runtime-images.txt
printf 'Offline images and source exported to %s; .env files and data volumes excluded.\n' "$archive_dir"
