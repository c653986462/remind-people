#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Usage: sudo bash update-server-tools.sh extracted-tools-package' >&2; exit 1; }
readonly ROOT="$(realpath "${1:?}")"
readonly TOOLS=/usr/local/lib/certificate-manager-ci
readonly SUDO_DEPLOY=/usr/local/sbin/certificate-manager-ci-deploy
readonly BACKUP="/opt/certificate-manager-ci-tools-backup-$(date +%Y%m%d-%H%M%S)-$$"
[[ -d "$ROOT/deploy/ci" && ! -L "$ROOT/deploy/ci" ]]
for file in setup-full-update.sh setup-email-reminders-update.sh verify-full-release.py; do [[ -f "$ROOT/deploy/$file" && ! -L "$ROOT/deploy/$file" ]]; done
for file in server-deploy.sh safe-extract.py verify-server-release.py; do [[ -f "$ROOT/deploy/ci/$file" && ! -L "$ROOT/deploy/ci/$file" ]]; done
systemctl is-active --quiet certificate-manager
install -d -m 0700 "$BACKUP"
cp -a "$TOOLS" "$BACKUP/"
cp -a "$SUDO_DEPLOY" "$BACKUP/"
for file in setup-full-update.sh setup-email-reminders-update.sh verify-full-release.py; do
    install -o root -g root -m 0644 "$ROOT/deploy/$file" "$TOOLS/$file"
done
for file in safe-extract.py verify-server-release.py; do
    install -o root -g root -m 0644 "$ROOT/deploy/ci/$file" "$TOOLS/$file"
done
install -o root -g root -m 0755 "$ROOT/deploy/ci/server-deploy.sh" "$SUDO_DEPLOY"
"/opt/certificate-manager/.venv/bin/python" -I -m py_compile "$TOOLS/safe-extract.py" "$TOOLS/verify-server-release.py" "$TOOLS/verify-full-release.py"
for file in "$TOOLS/setup-full-update.sh" "$TOOLS/setup-email-reminders-update.sh" "$SUDO_DEPLOY"; do bash -n "$file"; done
printf 'CI deployment tools updated. Previous root-owned tools: %s\n' "$BACKUP"
printf 'Set GitHub repository variable DEPLOY_SERVER_ONLY=true to enable small web/backend-only deployments.\n'
