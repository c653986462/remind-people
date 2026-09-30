#!/usr/bin/env bash
# Root-owned publisher: no API/scheduler restart and no Nginx traffic switch.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Expected a verified desktop artifact directory; run with sudo.' >&2; exit 1; }
readonly PACKAGE_ROOT="$(realpath "$1")"
readonly APP_DIR=/opt/certificate-manager
readonly TOOLS=/usr/local/lib/certificate-manager-ci
readonly UPDATE_DIR="$APP_DIR/desktop-updates"
exec 9>/run/lock/certificate-manager-deploy.lock
flock -x 9
"$APP_DIR/.venv/bin/python" -I "$TOOLS/verify-full-release.py" "$PACKAGE_ROOT"
readonly ACTIVE="$(readlink -f "$APP_DIR/current")"
[[ "$ACTIVE" == "$APP_DIR/releases/"* && -f "$ACTIVE/server-release.json" ]]
"$APP_DIR/.venv/bin/python" -I "$TOOLS/check-desktop-target.py" "$PACKAGE_ROOT" "$ACTIVE" "$UPDATE_DIR"
readonly VERSION="$("$APP_DIR/.venv/bin/python" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PACKAGE_ROOT/release.json")"
readonly INSTALLER="证事 Setup $VERSION.exe"
for filename in "$INSTALLER" "$INSTALLER.blockmap"; do
    [[ ! -L "$UPDATE_DIR/$filename" ]]
    if [[ -f "$UPDATE_DIR/$filename" ]] && ! cmp -s "$PACKAGE_ROOT/desktop-updates/$filename" "$UPDATE_DIR/$filename"; then
        echo 'This installer version already exists with different content; bump the version.' >&2
        exit 1
    fi
done
readonly BACKUP="/opt/certificate-manager-desktop-release-backup-$(date +%Y%m%d-%H%M%S)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$UPDATE_DIR/latest.yml" "$BACKUP/"
if [[ -f "$APP_DIR/release.json" ]]; then cp -a "$APP_DIR/release.json" "$BACKUP/"; fi
# Upload and verify everything before the atomic announcement. Existing installers
# and the current latest.yml stay available until this point.
for filename in "$INSTALLER" "$INSTALLER.blockmap"; do
    if [[ ! -f "$UPDATE_DIR/$filename" ]]; then
        install -o root -g www-data -m 0644 "$PACKAGE_ROOT/desktop-updates/$filename" "$UPDATE_DIR/.installer-next.$$"
        mv -Tf "$UPDATE_DIR/.installer-next.$$" "$UPDATE_DIR/$filename"
    fi
done
install -o root -g www-data -m 0644 "$PACKAGE_ROOT/release.json" "$APP_DIR/.release-next.$$"
mv -Tf "$APP_DIR/.release-next.$$" "$APP_DIR/release.json"
install -o root -g www-data -m 0644 "$PACKAGE_ROOT/desktop-updates/latest.yml" "$UPDATE_DIR/.latest-next.$$"
mv -Tf "$UPDATE_DIR/.latest-next.$$" "$UPDATE_DIR/latest.yml"
printf 'Desktop %s published without restarting web/API/scheduler. Metadata backup: %s\n' "$VERSION" "$BACKUP"
