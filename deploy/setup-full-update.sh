#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
readonly APP_DIR=/opt/certificate-manager
readonly PACKAGE_ROOT="$(realpath "${1:?Usage: sudo bash setup-full-update.sh extracted-release-directory}")"
[[ $EUID -eq 0 ]] || { printf 'Please run with sudo.\n' >&2; exit 1; }
readonly TOOLS_DIR="${CM_TRUSTED_DEPLOY_TOOLS:-$PACKAGE_ROOT/deploy}"
[[ -x "$TOOLS_DIR/blue-green-deploy.sh" ]] || { echo 'Blue/green server tools are not installed. Prepare and initialize them before deploying.' >&2; exit 1; }

# A release cannot proceed if any component or desktop checksum is missing.
"$APP_DIR/.venv/bin/python" -I "$TOOLS_DIR/verify-full-release.py" "$PACKAGE_ROOT"
release_version=$("$APP_DIR/.venv/bin/python" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PACKAGE_ROOT/release.json")
readonly INSTALLER="证事 Setup $release_version.exe"
readonly UPDATE_DIR="$APP_DIR/desktop-updates"
if [[ -f "$UPDATE_DIR/latest.yml" ]]; then
    "$APP_DIR/.venv/bin/python" -I - "$UPDATE_DIR/latest.yml" "$release_version" <<'PY'
import re, sys
from pathlib import Path
match = re.search(r'^version:\s*(\d+\.\d+\.\d+)\s*$', Path(sys.argv[1]).read_text(), re.M)
if not match:
    raise SystemExit('Cannot read the currently published version; check latest.yml first.')
version = lambda value: tuple(map(int, value.split('.')))
if version(sys.argv[2]) < version(match[1]):
    raise SystemExit('Refusing to downgrade the desktop release.')
PY
fi

# Do not mutate .env, data/, uploads, Nginx, or existing versioned installers.
chmod -R u=rwX,g=rX,o=rX "$PACKAGE_ROOT/app" "$PACKAGE_ROOT/frontend/dist"
install -d -o root -g www-data -m 0755 "$UPDATE_DIR"
for filename in "$INSTALLER" "$INSTALLER.blockmap"; do
    if [[ -f "$UPDATE_DIR/$filename" ]] && ! cmp -s "$PACKAGE_ROOT/desktop-updates/$filename" "$UPDATE_DIR/$filename"; then
        printf 'An installer with this version already exists but differs. Bump the release version.\n' >&2
        exit 1
    fi
done
# Prepare installer files first, but announce the version only after backend health passes.
install -o root -g www-data -m 0644 "$PACKAGE_ROOT/desktop-updates/$INSTALLER" "$PACKAGE_ROOT/desktop-updates/$INSTALLER.blockmap" "$UPDATE_DIR/"
readonly RELEASE_BACKUP="/opt/certificate-manager-full-release-backup-$(date +%Y%m%d-%H%M%S)-$$"
install -d -m 0700 "$RELEASE_BACKUP"
if [[ -f "$UPDATE_DIR/latest.yml" ]]; then cp -a "$UPDATE_DIR/latest.yml" "$RELEASE_BACKUP/"; fi
if [[ -f "$APP_DIR/release.json" ]]; then cp -a "$APP_DIR/release.json" "$RELEASE_BACKUP/"; fi

# Stage and health-check the inactive slot, then gracefully switch Nginx.
bash "$TOOLS_DIR/blue-green-deploy.sh" "$PACKAGE_ROOT" full
install -o root -g www-data -m 0644 "$PACKAGE_ROOT/release.json" "$APP_DIR/release.json"
install -o root -g www-data -m 0644 "$PACKAGE_ROOT/desktop-updates/latest.yml" "$UPDATE_DIR/.latest-full.tmp"
mv -f "$UPDATE_DIR/.latest-full.tmp" "$UPDATE_DIR/latest.yml"
printf 'Full release %s published: backend, web, download site, and desktop.\n' "$release_version"
printf 'Previous release metadata backup: %s\n' "$RELEASE_BACKUP"
printf 'Desktop users must accept/install the update; publishing does not silently replace a running app.\n'
