#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Usage: sudo bash setup-server.sh /tmp/github-actions.pub' >&2; exit 1; }
readonly PUBLIC_KEY="$(realpath "$1")"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
readonly ACCOUNT=certmgr-deploy
readonly CI_HOME=/var/lib/certificate-manager-ci
readonly TOOLS=/usr/local/lib/certificate-manager-ci
[[ -f "$PUBLIC_KEY" && ! -L "$PUBLIC_KEY" ]]
[[ "$(grep -c '^ssh-ed25519 ' "$PUBLIC_KEY")" -eq 1 && "$(wc -l < "$PUBLIC_KEY")" -eq 1 ]]
ssh-keygen -lf "$PUBLIC_KEY" >/dev/null
[[ -x /opt/certificate-manager/.venv/bin/python ]]
systemctl is-active --quiet certificate-manager
systemctl is-enabled --quiet certificate-manager-backup.timer
command -v flock >/dev/null
command -v visudo >/dev/null
if ! id "$ACCOUNT" >/dev/null 2>&1; then
    useradd --system --home-dir "$CI_HOME" --shell /bin/bash "$ACCOUNT"
fi
[[ "$(getent passwd "$ACCOUNT" | cut -d: -f6)" == "$CI_HOME" ]]
install -d -o root -g root -m 0755 "$CI_HOME" "$CI_HOME/.ssh" "$TOOLS"
install -d -o "$ACCOUNT" -g "$ACCOUNT" -m 0700 "$CI_HOME/incoming"
install -d -o root -g root -m 0700 "$CI_HOME/work"
readonly AUTH_FILE="$(mktemp "$CI_HOME/.ssh/authorized_keys.XXXXXX")"
printf 'no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty %s\n' "$(cat "$PUBLIC_KEY")" > "$AUTH_FILE"
install -o root -g root -m 0644 "$AUTH_FILE" "$CI_HOME/.ssh/authorized_keys"
rm -f -- "$AUTH_FILE"
for file in setup-full-update.sh setup-email-reminders-update.sh verify-full-release.py; do
    install -o root -g root -m 0644 "$DEPLOY_DIR/$file" "$TOOLS/$file"
done
install -o root -g root -m 0755 "$SCRIPT_DIR/blue-green-deploy.sh" "$TOOLS/blue-green-deploy.sh"
install -o root -g root -m 0755 "$SCRIPT_DIR/blue-green-rollback.sh" "$TOOLS/blue-green-rollback.sh"
install -o root -g root -m 0755 "$SCRIPT_DIR/publish-desktop.sh" "$TOOLS/publish-desktop.sh"
for file in check-release-order.py check-desktop-target.py; do
    install -o root -g root -m 0644 "$SCRIPT_DIR/$file" "$TOOLS/$file"
done
install -o root -g root -m 0644 "$SCRIPT_DIR/prepare-slot.py" "$TOOLS/prepare-slot.py"
install -o root -g root -m 0644 "$DEPLOY_DIR/certificate-manager@.service" "$TOOLS/certificate-manager@.service"
install -o root -g root -m 0644 "$DEPLOY_DIR/certificate-manager.service" "$TOOLS/certificate-manager.service"
install -o root -g root -m 0644 "$DEPLOY_DIR/certificate-manager-upstream.nginx.conf" "$TOOLS/certificate-manager-upstream.nginx.conf"
install -o root -g root -m 0644 "$SCRIPT_DIR/verify-server-release.py" "$TOOLS/verify-server-release.py"
install -o root -g root -m 0644 "$SCRIPT_DIR/safe-extract.py" "$TOOLS/safe-extract.py"
install -o root -g root -m 0755 "$SCRIPT_DIR/server-deploy.sh" /usr/local/sbin/certificate-manager-ci-deploy
readonly SUDOERS_STAGE="$(mktemp /tmp/certificate-manager-sudoers.XXXXXX)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/certificate-manager-ci-deploy *\n' "$ACCOUNT" > "$SUDOERS_STAGE"
visudo -cf "$SUDOERS_STAGE"
install -o root -g root -m 0440 "$SUDOERS_STAGE" /etc/sudoers.d/certificate-manager-ci
rm -f -- "$SUDOERS_STAGE"
printf 'CI account ready: %s. SSH key allows deployment without general root access.\n' "$ACCOUNT"
printf 'Copy the following known-host line into DEPLOY_KNOWN_HOSTS after verifying it on this server:\n'
awk '{print "124.221.168.72 " $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
