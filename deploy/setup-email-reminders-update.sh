#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly APP_DIR=/opt/certificate-manager
readonly PACKAGE_ROOT="${1:?用法: sudo bash setup-email-reminders-update.sh 已解压的更新目录}"
readonly UPDATE_ID="$(date +%Y%m%d-%H%M%S)-$$"
readonly BACKUP_DIR="/opt/certificate-manager-email-update-backup-$UPDATE_ID"

[[ $EUID -eq 0 ]] || { printf '请使用 sudo 运行。\n' >&2; exit 1; }
[[ -f "$APP_DIR/.env" && -x "$APP_DIR/.venv/bin/python" && -f "$PACKAGE_ROOT/app/main.py" ]]
[[ -f "$PACKAGE_ROOT/frontend/dist/index.html" && -f "$PACKAGE_ROOT/requirements.txt" ]]
systemctl is-active --quiet certificate-manager

# Save an online SQLite backup before the additive email tables are created.
systemctl start certificate-manager-backup.service
journalctl -u certificate-manager-backup.service -n 15 --no-pager | grep -q 'Backup succeeded:'

install -d -o root -g root -m 0700 "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/code-before.tar.gz" --exclude=app/__pycache__ -C "$APP_DIR" app frontend/dist requirements.txt
chmod 0600 "$BACKUP_DIR/code-before.tar.gz"
printf '代码回滚备份：%s/code-before.tar.gz\n' "$BACKUP_DIR"

rollback() {
    tar --no-same-owner -xzf "$BACKUP_DIR/code-before.tar.gz" -C "$APP_DIR"
    chown -R root:www-data "$APP_DIR/app" "$APP_DIR/frontend/dist"
    systemctl restart certificate-manager || true
}

if ! cp -a "$PACKAGE_ROOT/app/." "$APP_DIR/app/" \
    || ! cp -a "$PACKAGE_ROOT/frontend/dist/." "$APP_DIR/frontend/dist/" \
    || ! install -m 0644 "$PACKAGE_ROOT/requirements.txt" "$APP_DIR/requirements.txt"; then
    rollback
    exit 1
fi
chown -R root:www-data "$APP_DIR/app" "$APP_DIR/frontend/dist"

if ! "$APP_DIR/.venv/bin/python" -m py_compile "$APP_DIR/app/main.py" "$APP_DIR/app/models.py" "$APP_DIR/app/services.py" "$APP_DIR/app/email_service.py"; then
    rollback
    exit 1
fi
if ! systemctl restart certificate-manager; then
    rollback
    exit 1
fi

healthy=false
for attempt in {1..20}; do
    if curl --noproxy '*' -fsS -H 'Host: xueqin.xyz' --connect-timeout 2 --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
        healthy=true
        break
    fi
    sleep 1
done
if [[ "$healthy" != true ]] || ! systemctl is-active --quiet certificate-manager; then
    rollback
    printf '服务健康检查失败，已恢复更新前代码。\n' >&2
    exit 1
fi
printf '后端服务运行正常。\n'
systemctl status certificate-manager --no-pager -l
printf '代码回滚备份保留在：%s\n' "$BACKUP_DIR"
