#!/usr/bin/env bash
# Switch public traffic back to the retained standby release.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $# -eq 0 ]] || { echo 'Run with sudo and no arguments.' >&2; exit 1; }
readonly APP_DIR=/opt/certificate-manager
readonly STATE_DIR=/var/lib/certificate-manager-ci
readonly STATE_FILE="$STATE_DIR/active-slot"
readonly BACKEND=/etc/nginx/certificate-manager-backend.current
readonly ROOT_CONF=/etc/nginx/certificate-manager-root.current
exec 9>/run/lock/certificate-manager-deploy.lock
flock -x 9
readonly ACTIVE="$(<"$STATE_FILE")"
[[ "$ACTIVE" == blue || "$ACTIVE" == green ]]
readonly PREVIOUS="$([[ "$ACTIVE" == blue ]] && echo green || echo blue)"
readonly ACTIVE_PORT="$([[ "$ACTIVE" == blue ]] && echo 8001 || echo 8002)"
readonly PREVIOUS_PORT="$([[ "$PREVIOUS" == blue ]] && echo 8001 || echo 8002)"
readonly PREVIOUS_RELEASE="$(readlink -f "$APP_DIR/slots/$PREVIOUS")"
[[ "$PREVIOUS_RELEASE" == "$APP_DIR/releases/"* && -f "$PREVIOUS_RELEASE/app/main.py" ]]
systemctl is-active --quiet "certificate-manager@$PREVIOUS.service"
curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 5 "http://127.0.0.1:$PREVIOUS_PORT/health" >/dev/null
readonly SAVE="$STATE_DIR/.rollback-save.$$"
install -d -m 0700 "$SAVE"
cp -a "$APP_DIR/current" "$BACKEND" "$ROOT_CONF" "$STATE_FILE" "$SAVE/"

atomic_link() {
    local target="$1" link="$2" tmp="${2}.rollback.$$"
    ln -s "$target" "$tmp"
    mv -Tf "$tmp" "$link"
}
restore_active() {
    atomic_link "$(readlink -f "$SAVE/current")" "$APP_DIR/current" || true
    cp -a "$SAVE/certificate-manager-backend.current" "$BACKEND.rollback.$$" || true
    mv -fT "$BACKEND.rollback.$$" "$BACKEND" || true
    cp -a "$SAVE/certificate-manager-root.current" "$ROOT_CONF.rollback.$$" || true
    mv -fT "$ROOT_CONF.rollback.$$" "$ROOT_CONF" || true
    cp -a "$SAVE/active-slot" "$STATE_FILE.rollback.$$" || true
    mv -fT "$STATE_FILE.rollback.$$" "$STATE_FILE" || true
    nginx -t && systemctl reload nginx || true
    systemctl restart certificate-manager || true
}
switched=false
on_error() {
    code=$?
    trap - ERR
    [[ "$switched" == true ]] && restore_active
    echo 'Rollback did not complete; previous active slot was restored where possible.' >&2
    exit "$code"
}
trap on_error ERR
switched=true
atomic_link "$PREVIOUS_RELEASE" "$APP_DIR/current"
printf 'server 127.0.0.1:%s;\n' "$PREVIOUS_PORT" > "$BACKEND.rollback.$$"
mv -fT "$BACKEND.rollback.$$" "$BACKEND"
printf 'root %s/frontend/dist;\n' "$PREVIOUS_RELEASE" > "$ROOT_CONF.rollback.$$"
mv -fT "$ROOT_CONF.rollback.$$" "$ROOT_CONF"
nginx -t
systemctl reload nginx
printf '%s\n' "$PREVIOUS" > "$STATE_FILE.rollback.$$"
chmod 0600 "$STATE_FILE.rollback.$$"
mv -fT "$STATE_FILE.rollback.$$" "$STATE_FILE"
for attempt in {1..120}; do
    if ! ss -Hnt state established '( sport = :8000 )' | grep -q .; then break; fi
    if [[ "$attempt" -eq 120 ]]; then false; fi
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
trap - ERR
printf 'Traffic rolled back from %s (%s) to %s (%s). Both releases remain on disk.\n' "$ACTIVE" "$ACTIVE_PORT" "$PREVIOUS" "$PREVIOUS_PORT"
