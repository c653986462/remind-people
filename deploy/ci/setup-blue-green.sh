#!/usr/bin/env bash
# One-time migration on the Ubuntu server. Run from a reviewed tools package.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
readonly APP_DIR=/opt/certificate-manager
readonly TOOLS=/usr/local/lib/certificate-manager-ci
readonly STATE_DIR=/var/lib/certificate-manager-ci
readonly BACKUP="/opt/certificate-manager-bluegreen-bootstrap-backup-$(date +%Y%m%d-%H%M%S)-$$"
[[ -f "$APP_DIR/.env" && -x "$APP_DIR/.venv/bin/uvicorn" && -d "$APP_DIR/app" && -f "$APP_DIR/frontend/dist/index.html" ]]
systemctl is-active --quiet certificate-manager
systemctl is-active --quiet nginx
install -d -o root -g root -m 0700 "$BACKUP"
install -d -o root -g root -m 0755 "$STATE_DIR" "$APP_DIR/releases" "$APP_DIR/slots" /etc/certificate-manager /etc/nginx/conf.d
cp -a /etc/systemd/system/certificate-manager.service "$BACKUP/certificate-manager.service"
if [[ -L "$APP_DIR/current" ]]; then cp -a "$APP_DIR/current" "$BACKUP/current"; fi
mkdir -p "$BACKUP/sites"

declare -a site_files=()
while IFS= read -r -d '' enabled; do
    target="$(readlink -f "$enabled")"
    [[ -f "$target" && ! -L "$target" ]] || continue
    if grep -qE 'root /opt/certificate-manager/frontend/dist;|proxy_pass http://127\.0\.0\.1:8000(/[^;]*)?;' "$target"; then
        site_files+=("$target")
    fi
done < <(find /etc/nginx/sites-enabled -maxdepth 1 \( -type f -o -type l \) -print0)
[[ ${#site_files[@]} -gt 0 ]] || { echo 'Could not find enabled Certificate Manager Nginx site files to migrate.' >&2; exit 1; }
for file in "${site_files[@]}"; do cp -a "$file" "$BACKUP/sites/$(basename "$file")"; done
if [[ -f /etc/nginx/conf.d/certificate-manager-upstream.conf ]]; then cp -a /etc/nginx/conf.d/certificate-manager-upstream.conf "$BACKUP/"; fi
if [[ -f /etc/nginx/certificate-manager-backend.current ]]; then cp -a /etc/nginx/certificate-manager-backend.current "$BACKUP/"; fi
if [[ -f /etc/nginx/certificate-manager-root.current ]]; then cp -a /etc/nginx/certificate-manager-root.current "$BACKUP/"; fi

rollback() {
    code=$?
    trap - ERR
    for file in "${site_files[@]}"; do
        backup_file="$BACKUP/sites/$(basename "$file")"
        [[ -f "$backup_file" ]] && cp -a "$backup_file" "$file"
    done
    if [[ -f "$BACKUP/certificate-manager-upstream.conf" ]]; then cp -a "$BACKUP/certificate-manager-upstream.conf" /etc/nginx/conf.d/certificate-manager-upstream.conf; else rm -f /etc/nginx/conf.d/certificate-manager-upstream.conf; fi
    if [[ -f "$BACKUP/certificate-manager-backend.current" ]]; then cp -a "$BACKUP/certificate-manager-backend.current" /etc/nginx/certificate-manager-backend.current; else rm -f /etc/nginx/certificate-manager-backend.current; fi
    if [[ -f "$BACKUP/certificate-manager-root.current" ]]; then cp -a "$BACKUP/certificate-manager-root.current" /etc/nginx/certificate-manager-root.current; else rm -f /etc/nginx/certificate-manager-root.current; fi
    cp -a "$BACKUP/certificate-manager.service" /etc/systemd/system/certificate-manager.service
    if [[ -L "$BACKUP/current" ]]; then
        old_current="$(readlink "$BACKUP/current")"
        tmp_current="$APP_DIR/current.rollback.$$"
        ln -s "$old_current" "$tmp_current"
        mv -Tf "$tmp_current" "$APP_DIR/current"
    elif [[ -L "$APP_DIR/current" ]]; then
        rm -f "$APP_DIR/current"
    fi
    systemctl daemon-reload || true
    nginx -t && systemctl reload nginx || true
    systemctl restart certificate-manager || true
    systemctl stop certificate-manager@blue.service certificate-manager@green.service || true
    echo "Initial blue/green setup failed; original Nginx/service configuration restored. Backup: $BACKUP" >&2
    exit "$code"
}
trap rollback ERR

release_id="bootstrap-$(date +%Y%m%d%H%M%S)"
readonly RELEASE="$APP_DIR/releases/$release_id"
install -d -o root -g root -m 0755 "$RELEASE"
cp -a "$APP_DIR/app" "$APP_DIR/frontend" "$RELEASE/"
install -m 0644 "$APP_DIR/requirements.txt" "$RELEASE/requirements.txt"
"$APP_DIR/.venv/bin/python" -I "$TOOLS/prepare-slot.py" "$RELEASE"
chown -R root:www-data "$RELEASE"
find "$RELEASE" -type d -exec chmod 0750 {} +
find "$RELEASE" -type f -exec chmod 0640 {} +

install -o root -g root -m 0644 "$TOOLS/certificate-manager@.service" /etc/systemd/system/certificate-manager@.service
install -o root -g root -m 0644 "$TOOLS/certificate-manager.service" /etc/systemd/system/certificate-manager.service
install -o root -g root -m 0644 "$TOOLS/certificate-manager-upstream.nginx.conf" /etc/nginx/conf.d/certificate-manager-upstream.conf
atomic_link() {
    local target="$1" link="$2" tmp="${2}.next.$$"
    ln -s "$target" "$tmp"
    mv -Tf "$tmp" "$link"
}
atomic_link "$RELEASE" "$APP_DIR/current"
atomic_link "$RELEASE" "$APP_DIR/slots/blue"
atomic_link "$RELEASE" "$APP_DIR/slots/green"
printf 'PORT=8001\nDATABASE_URL=sqlite:////opt/certificate-manager/data/certificates.db\nSCHEDULER_ENABLED=false\n' > /etc/certificate-manager/slot-blue.conf
printf 'PORT=8002\nDATABASE_URL=sqlite:////opt/certificate-manager/data/certificates.db\nSCHEDULER_ENABLED=false\n' > /etc/certificate-manager/slot-green.conf
chmod 0640 /etc/certificate-manager/slot-blue.conf /etc/certificate-manager/slot-green.conf
chown root:www-data /etc/certificate-manager/slot-blue.conf /etc/certificate-manager/slot-green.conf
printf 'blue\n' > "$STATE_DIR/active-slot"
chmod 0600 "$STATE_DIR/active-slot"
printf 'server 127.0.0.1:8001;\n' > /etc/nginx/certificate-manager-backend.current
chmod 0644 /etc/nginx/certificate-manager-backend.current
printf 'root %s/frontend/dist;\n' "$RELEASE" > /etc/nginx/certificate-manager-root.current
chmod 0644 /etc/nginx/certificate-manager-root.current

for file in "${site_files[@]}"; do
    python3 - "$file" <<'PY'
from pathlib import Path
import re, sys
path = Path(sys.argv[1])
text = path.read_text()
text, roots = re.subn(r'root\s+/opt/certificate-manager/frontend/dist\s*;', 'include /etc/nginx/certificate-manager-root.current;', text)
text, proxies = re.subn(r'proxy_pass\s+http://127\.0\.0\.1:8000(/[^;]*)?;', lambda m: 'proxy_pass http://certificate_manager_active' + (m.group(1) or '/') + ';', text)
if roots < 1 or proxies < 2:
    raise SystemExit(f'Refusing unexpected Nginx layout in {path}: roots={roots}, api proxies={proxies}')
path.write_text(text)
PY
done

systemctl daemon-reload
for slot_port in 'blue:8001' 'green:8002'; do
    slot="${slot_port%%:*}"
    port="${slot_port##*:}"
    systemctl enable --now "certificate-manager@$slot.service"
    healthy=false
    for attempt in {1..30}; do
        if curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 3 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then healthy=true; break; fi
        sleep 1
    done
    [[ "$healthy" == true ]]
done

nginx -t
systemctl reload nginx
curl --noproxy '*' -kfsS --resolve xueqin.xyz:443:127.0.0.1 --connect-timeout 2 --max-time 5 https://xueqin.xyz/api/health >/dev/null
curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 5 http://127.0.0.1:8001/health >/dev/null
trap - ERR
printf 'Blue/green is initialized. Public traffic uses blue on 8001; green on 8002 is ready. Existing scheduler on 8000 was left running and is the only reminder scheduler.\n'
printf 'Bootstrap backup: %s\n' "$BACKUP"
