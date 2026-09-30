#!/usr/bin/env bash
# Root-owned deployment entrypoint. Only the immutable package snapshot prepared by
# server-deploy.sh is accepted here; uploaded hooks are never executed.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $# -eq 2 ]] || { echo 'Expected a verified release directory and kind (server|full).' >&2; exit 1; }
readonly PACKAGE_ROOT="$(realpath "${1:?}")"
readonly RELEASE_KIND="$2"
readonly APP_DIR=/opt/certificate-manager
readonly TOOLS=/usr/local/lib/certificate-manager-ci
readonly STATE_DIR=/var/lib/certificate-manager-ci
readonly SLOT_DIR="$APP_DIR/slots"
readonly RELEASES="$APP_DIR/releases"
readonly STATE_FILE="$STATE_DIR/active-slot"
[[ "$RELEASE_KIND" == server || "$RELEASE_KIND" == full ]]
[[ -d "$PACKAGE_ROOT/app" && -f "$PACKAGE_ROOT/app/main.py" && -f "$PACKAGE_ROOT/frontend/dist/index.html" && -f "$PACKAGE_ROOT/requirements.txt" ]]
[[ -L "$APP_DIR/current" && -f "$STATE_FILE" && -f /etc/nginx/certificate-manager-backend.current && -f /etc/nginx/certificate-manager-root.current ]] || {
    echo 'Blue/green is not initialized. Run the one-time setup-blue-green.sh on the server first.' >&2
    exit 1
}
exec 9>/run/lock/certificate-manager-deploy.lock
flock -x 9

readonly ACTIVE_SLOT="$(<"$STATE_FILE")"
[[ "$ACTIVE_SLOT" == blue || "$ACTIVE_SLOT" == green ]]
readonly CANDIDATE_SLOT="$([[ "$ACTIVE_SLOT" == blue ]] && echo green || echo blue)"
readonly OLD_CURRENT="$(readlink -f "$APP_DIR/current")"
[[ "$OLD_CURRENT" == "$RELEASES"/* ]]
if [[ "$RELEASE_KIND" == server ]]; then
    "$APP_DIR/.venv/bin/python" -I "$TOOLS/check-release-order.py" "$PACKAGE_ROOT/server-release.json" "$OLD_CURRENT/server-release.json"
fi
readonly ACTIVE_PORT="$([[ "$ACTIVE_SLOT" == blue ]] && echo 8001 || echo 8002)"
readonly CANDIDATE_PORT="$([[ "$CANDIDATE_SLOT" == blue ]] && echo 8001 || echo 8002)"
readonly RELEASE_TAG="$(date +%Y%m%d%H%M%S)-$$"
readonly NEW_RELEASE="$RELEASES/$RELEASE_TAG"
readonly BACKUP_DIR="/opt/certificate-manager-bluegreen-backup-$RELEASE_TAG"
install -d -o root -g root -m 0755 "$RELEASES" "$SLOT_DIR"
[[ ! -e "$NEW_RELEASE" && ! -L "$NEW_RELEASE" ]]

systemctl start certificate-manager-backup.service
journalctl -u certificate-manager-backup.service -n 20 --no-pager | grep -q 'Backup succeeded:'

install -d -o root -g root -m 0700 "$BACKUP_DIR"
cp -a "$STATE_FILE" "$BACKUP_DIR/active-slot"
cp -a /etc/nginx/certificate-manager-backend.current "$BACKUP_DIR/backend.current"
cp -a /etc/nginx/certificate-manager-root.current "$BACKUP_DIR/root.current"
printf 'Previous active release: %s\n' "$OLD_CURRENT" > "$BACKUP_DIR/release.txt"
mkdir -m 0755 "$NEW_RELEASE"
cp -a "$PACKAGE_ROOT/app" "$NEW_RELEASE/app"
cp -a "$PACKAGE_ROOT/frontend" "$NEW_RELEASE/frontend"
install -m 0644 "$PACKAGE_ROOT/requirements.txt" "$NEW_RELEASE/requirements.txt"
if [[ "$RELEASE_KIND" == server ]]; then
    install -m 0644 "$PACKAGE_ROOT/server-release.json" "$NEW_RELEASE/server-release.json"
else
    install -m 0644 "$PACKAGE_ROOT/release.json" "$NEW_RELEASE/release.json"
fi
"$APP_DIR/.venv/bin/python" -I "$TOOLS/prepare-slot.py" "$NEW_RELEASE"
# Preserve hashed Vite assets referenced by already-open tabs in old worker processes.
if [[ -d "$OLD_CURRENT/frontend/dist/assets" ]]; then
    install -d "$NEW_RELEASE/frontend/dist/assets"
    cp -an "$OLD_CURRENT/frontend/dist/assets/." "$NEW_RELEASE/frontend/dist/assets/"
fi
chown -R root:www-data "$NEW_RELEASE"
find "$NEW_RELEASE" -type d -exec chmod 0750 {} +
find "$NEW_RELEASE" -type f -exec chmod 0640 {} +
"$APP_DIR/.venv/bin/python" -I -m py_compile "$NEW_RELEASE/app/main.py" "$NEW_RELEASE/app/models.py" "$NEW_RELEASE/app/services.py" "$NEW_RELEASE/app/email_service.py"

# Wait until old Nginx workers have drained connections to the inactive slot
# before replacing its process. If it cannot drain, fail without touching live traffic.
for attempt in {1..120}; do
    if ! ss -Hnt state established "( sport = :$CANDIDATE_PORT )" | grep -q .; then break; fi
    if [[ "$attempt" -eq 120 ]]; then
        echo "Inactive slot $CANDIDATE_SLOT still has established clients; refusing to interrupt it." >&2
        exit 1
    fi
    sleep 1
done
systemctl stop "certificate-manager@$CANDIDATE_SLOT.service"
atomic_symlink() {
    local target="$1" link="$2" tmp="${2}.next.$$"
    ln -s "$target" "$tmp"
    mv -Tf "$tmp" "$link"
}
atomic_symlink "$NEW_RELEASE" "$SLOT_DIR/$CANDIDATE_SLOT"

switched=false
rollback() {
    local code=$?
    trap - ERR
    if [[ "$switched" == true ]]; then
        atomic_symlink "$OLD_CURRENT" "$APP_DIR/current" || true
        printf 'server 127.0.0.1:%s;\n' "$ACTIVE_PORT" > /etc/nginx/.certificate-manager-backend.rollback.$$
        mv -fT /etc/nginx/.certificate-manager-backend.rollback.$$ /etc/nginx/certificate-manager-backend.current || true
        cp -a "$BACKUP_DIR/root.current" /etc/nginx/.certificate-manager-root.rollback.$$
        mv -fT /etc/nginx/.certificate-manager-root.rollback.$$ /etc/nginx/certificate-manager-root.current || true
        nginx -t && systemctl reload nginx || true
        printf '%s\n' "$ACTIVE_SLOT" > "$STATE_DIR/.active-slot.rollback.$$"
        chmod 0600 "$STATE_DIR/.active-slot.rollback.$$"
        mv -fT "$STATE_DIR/.active-slot.rollback.$$" "$STATE_FILE" || true
        systemctl restart certificate-manager || true
    fi
    if [[ "$switched" == false ]]; then
        systemctl stop "certificate-manager@$CANDIDATE_SLOT.service" || true
    fi
    echo "Blue/green deploy failed; previous public slot $ACTIVE_SLOT remains active. New release kept at $NEW_RELEASE for diagnosis." >&2
    exit "$code"
}
trap rollback ERR
systemctl start "certificate-manager@$CANDIDATE_SLOT.service"
healthy=false
for attempt in {1..30}; do
    if curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 3 "http://127.0.0.1:$CANDIDATE_PORT/health" >/dev/null 2>&1; then
        healthy=true
        break
    fi
    sleep 1
done
[[ "$healthy" == true ]]
systemctl is-active --quiet "certificate-manager@$CANDIDATE_SLOT.service"

# Stage both pointers, validate Nginx, and only then gracefully reload workers.
switched=true
atomic_symlink "$NEW_RELEASE" "$APP_DIR/current"
printf 'server 127.0.0.1:%s;\n' "$CANDIDATE_PORT" > /etc/nginx/.certificate-manager-backend.next.$$
mv -fT /etc/nginx/.certificate-manager-backend.next.$$ /etc/nginx/certificate-manager-backend.current
printf 'root %s/frontend/dist;\n' "$NEW_RELEASE" > /etc/nginx/.certificate-manager-root.next.$$
mv -fT /etc/nginx/.certificate-manager-root.next.$$ /etc/nginx/certificate-manager-root.current
nginx -t
systemctl reload nginx
printf '%s\n' "$CANDIDATE_SLOT" > "$STATE_DIR/.active-slot.next.$$"
chown root:root "$STATE_DIR/.active-slot.next.$$"
chmod 0600 "$STATE_DIR/.active-slot.next.$$"
mv -fT "$STATE_DIR/.active-slot.next.$$" "$STATE_FILE"

# This is the sole scheduler process. Its restart is isolated from public traffic.
for attempt in {1..120}; do
    if ! ss -Hnt state established '( sport = :8000 )' | grep -q .; then break; fi
    if [[ "$attempt" -eq 120 ]]; then
        echo 'Pre-cutover Nginx connections to the scheduler port have not drained.' >&2
        false
    fi
    sleep 1
done
systemctl restart certificate-manager
healthy=false
for attempt in {1..30}; do
    if curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then healthy=true; break; fi
    sleep 1
done
[[ "$healthy" == true ]]
systemctl is-active --quiet certificate-manager
curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 5 "http://127.0.0.1:$CANDIDATE_PORT/health" >/dev/null
curl --noproxy '*' -kfsS --resolve xueqin.xyz:443:127.0.0.1 --connect-timeout 2 --max-time 5 https://xueqin.xyz/api/health >/dev/null
trap - ERR
switched=false

printf 'Blue/green release is live. Active slot: %s (127.0.0.1:%s); previous slot: %s remains running for rollback.\n' "$CANDIDATE_SLOT" "$CANDIDATE_PORT" "$ACTIVE_SLOT"
printf 'Release retained: %s\nRollback backup: %s\n' "$NEW_RELEASE" "$BACKUP_DIR"
