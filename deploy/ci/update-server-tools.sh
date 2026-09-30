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
for file in server-deploy.sh safe-extract.py verify-server-release.py prepare-slot.py check-release-order.py check-desktop-target.py publish-desktop.sh; do [[ -f "$ROOT/deploy/ci/$file" && ! -L "$ROOT/deploy/ci/$file" ]]; done
[[ -f "$ROOT/deploy/ci/blue-green-deploy.sh" && ! -L "$ROOT/deploy/ci/blue-green-deploy.sh" ]]
[[ -f "$ROOT/deploy/ci/blue-green-rollback.sh" && ! -L "$ROOT/deploy/ci/blue-green-rollback.sh" ]]
for file in certificate-manager.service certificate-manager@.service certificate-manager-upstream.nginx.conf; do [[ -f "$ROOT/deploy/$file" && ! -L "$ROOT/deploy/$file" ]]; done
systemctl is-active --quiet certificate-manager
# Validate the candidate tools before changing the installed trusted entrypoint.
for file in "$ROOT/deploy/setup-full-update.sh" "$ROOT/deploy/setup-email-reminders-update.sh" "$ROOT/deploy/ci/blue-green-deploy.sh" "$ROOT/deploy/ci/blue-green-rollback.sh" "$ROOT/deploy/ci/server-deploy.sh" "$ROOT/deploy/ci/publish-desktop.sh"; do bash -n "$file"; done
"/opt/certificate-manager/.venv/bin/python" -I - "$ROOT" <<'PY'
from pathlib import Path
import sys
for path in (Path(sys.argv[1]) / 'deploy').rglob('*.py'):
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
PY
install -d -m 0700 "$BACKUP"
cp -a "$TOOLS" "$BACKUP/"
cp -a "$SUDO_DEPLOY" "$BACKUP/"
for file in setup-full-update.sh setup-email-reminders-update.sh verify-full-release.py; do
    install -o root -g root -m 0644 "$ROOT/deploy/$file" "$TOOLS/$file"
done
for file in safe-extract.py verify-server-release.py prepare-slot.py check-release-order.py check-desktop-target.py; do
    install -o root -g root -m 0644 "$ROOT/deploy/ci/$file" "$TOOLS/$file"
done
install -o root -g root -m 0755 "$ROOT/deploy/ci/blue-green-deploy.sh" "$TOOLS/blue-green-deploy.sh"
install -o root -g root -m 0755 "$ROOT/deploy/ci/blue-green-rollback.sh" "$TOOLS/blue-green-rollback.sh"
install -o root -g root -m 0755 "$ROOT/deploy/ci/publish-desktop.sh" "$TOOLS/publish-desktop.sh"
for file in certificate-manager.service certificate-manager@.service certificate-manager-upstream.nginx.conf; do
    install -o root -g root -m 0644 "$ROOT/deploy/$file" "$TOOLS/$file"
done
install -o root -g root -m 0755 "$ROOT/deploy/ci/server-deploy.sh" "$SUDO_DEPLOY"
"/opt/certificate-manager/.venv/bin/python" -I -m py_compile "$TOOLS/safe-extract.py" "$TOOLS/verify-server-release.py" "$TOOLS/verify-full-release.py" "$TOOLS/prepare-slot.py" "$TOOLS/check-release-order.py" "$TOOLS/check-desktop-target.py"
for file in "$TOOLS/setup-full-update.sh" "$TOOLS/setup-email-reminders-update.sh" "$TOOLS/blue-green-deploy.sh" "$TOOLS/blue-green-rollback.sh" "$TOOLS/publish-desktop.sh" "$SUDO_DEPLOY"; do bash -n "$file"; done
printf 'Split publication is ready: web/API blue-green deployment; desktop-only atomic metadata publication without service restarts.\n'
printf 'CI deployment tools updated. Previous root-owned tools: %s\n' "$BACKUP"
printf 'Set GitHub repository variable DEPLOY_SERVER_ONLY=true to enable small web/backend-only deployments.\n'
if [[ -f /var/lib/certificate-manager-ci/active-slot ]]; then
    printf 'Blue/green is already initialized. Apply repair-blue-green.sh if upgrading from the first bootstrap package.\n'
else
    printf 'After updating these tools, run setup-blue-green.sh once to migrate live Nginx traffic.\n'
fi
