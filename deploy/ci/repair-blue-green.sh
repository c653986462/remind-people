#!/usr/bin/env bash
# Repair a previously initialized server while one public slot keeps serving.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
readonly APP_DIR=/opt/certificate-manager
readonly TOOLS=/usr/local/lib/certificate-manager-ci
readonly STATE=/var/lib/certificate-manager-ci/active-slot
readonly BACKEND=/etc/nginx/certificate-manager-backend.current
readonly ROOT_CONF=/etc/nginx/certificate-manager-root.current
exec 9>/run/lock/certificate-manager-deploy.lock
flock -x 9
readonly ACTIVE="$(<"$STATE")"
[[ "$ACTIVE" == blue || "$ACTIVE" == green ]]
readonly STANDBY="$([[ "$ACTIVE" == blue ]] && echo green || echo blue)"
readonly ACTIVE_PORT="$([[ "$ACTIVE" == blue ]] && echo 8001 || echo 8002)"
readonly STANDBY_PORT="$([[ "$STANDBY" == blue ]] && echo 8001 || echo 8002)"
readonly OLD_CURRENT="$(readlink -f "$APP_DIR/current")"
readonly STANDBY_RELEASE="$(readlink -f "$APP_DIR/slots/$STANDBY")"
readonly BACKUP="/opt/certificate-manager-bluegreen-repair-backup-$(date +%Y%m%d-%H%M%S)-$$"
systemctl is-active --quiet nginx
systemctl is-active --quiet certificate-manager
systemctl is-active --quiet "certificate-manager@$ACTIVE.service"
install -d -m 0700 "$BACKUP"
cp -a "$BACKEND" "$ROOT_CONF" "$STATE" "$BACKUP/"
cp -a /etc/systemd/system/certificate-manager.service /etc/systemd/system/certificate-manager@.service "$BACKUP/"

wait_drained() {
    local port="$1" connections
    for attempt in {1..120}; do
        connections="$(ss -Hnt state established "( sport = :$port )")"
        [[ -z "$connections" ]] && return 0
        sleep 1
    done
    echo "Port $port still has connections; leaving its process running." >&2
    return 1
}
atomic_link() {
    local target="$1" link="$2" tmp="${2}.repair.$$"
    ln -s "$target" "$tmp"
    mv -Tf "$tmp" "$link"
}
switched=false
on_error() {
    local code=$?
    trap - ERR
    if [[ "$switched" == true ]]; then
        atomic_link "$OLD_CURRENT" "$APP_DIR/current" || true
        for file in "$BACKEND" "$ROOT_CONF" "$STATE"; do
            cp -a "$BACKUP/$(basename "$file")" "$file.repair.$$" || true
            mv -fT "$file.repair.$$" "$file" || true
        done
        nginx -t && systemctl reload nginx || true
    fi
    echo "Repair failed; existing public configuration restored where possible. Both slot processes are retained. Backup: $BACKUP" >&2
    exit "$code"
}
trap on_error ERR

# Only patch the startup scheduler guard in legacy immutable release copies.
# The existing processes keep their already-loaded code until each slot drains.
for slot in "$STANDBY" "$ACTIVE"; do
    "$APP_DIR/.venv/bin/python" -I "$TOOLS/prepare-slot.py" "$(readlink -f "$APP_DIR/slots/$slot")"
done
install -o root -g root -m 0644 "$TOOLS/certificate-manager@.service" /etc/systemd/system/certificate-manager@.service
install -o root -g root -m 0644 "$TOOLS/certificate-manager.service" /etc/systemd/system/certificate-manager.service
systemctl daemon-reload

wait_drained "$STANDBY_PORT"
systemctl restart "certificate-manager@$STANDBY.service"
healthy=false
for attempt in {1..30}; do
    if curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 3 "http://127.0.0.1:$STANDBY_PORT/health" >/dev/null 2>&1; then healthy=true; break; fi
    sleep 1
done
[[ "$healthy" == true ]]

switched=true
atomic_link "$STANDBY_RELEASE" "$APP_DIR/current"
printf 'server 127.0.0.1:%s;\n' "$STANDBY_PORT" > "$BACKEND.repair.$$"
mv -fT "$BACKEND.repair.$$" "$BACKEND"
printf 'root %s/frontend/dist;\n' "$STANDBY_RELEASE" > "$ROOT_CONF.repair.$$"
mv -fT "$ROOT_CONF.repair.$$" "$ROOT_CONF"
nginx -t
systemctl reload nginx
curl --noproxy '*' -kfsS --resolve xueqin.xyz:443:127.0.0.1 --connect-timeout 2 --max-time 5 https://xueqin.xyz/api/health >/dev/null
printf '%s\n' "$STANDBY" > "$STATE.repair.$$"
chmod 0600 "$STATE.repair.$$"
mv -fT "$STATE.repair.$$" "$STATE"
# From here the repaired standby is public. Keep it active even if fixing the
# other slot fails, rather than putting users back onto the old process.
switched=false
wait_drained "$ACTIVE_PORT"
systemctl restart "certificate-manager@$ACTIVE.service"
healthy=false
for attempt in {1..30}; do
    if curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 3 "http://127.0.0.1:$ACTIVE_PORT/health" >/dev/null 2>&1; then healthy=true; break; fi
    sleep 1
done
[[ "$healthy" == true ]]
trap - ERR
printf 'Repair complete. Public slot: %s. Both API slots load their explicit release directories and disable scheduled reminders. Original scheduler on 8000 was left running.\n' "$STANDBY"
printf 'Backup: %s\n' "$BACKUP"
