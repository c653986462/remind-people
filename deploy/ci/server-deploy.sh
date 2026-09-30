#!/usr/bin/env bash
# Installed root-owned at /usr/local/sbin/certificate-manager-ci-deploy.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $# -eq 2 ]] || { echo 'Expected an archive and its SHA256; run with sudo.' >&2; exit 1; }
readonly ARCHIVE="$1"
readonly DIGEST="$2"
readonly INCOMING=/var/lib/certificate-manager-ci/incoming
readonly WORK_DIR=/var/lib/certificate-manager-ci/work
readonly TOOLS=/usr/local/lib/certificate-manager-ci
readonly APP_DIR=/opt/certificate-manager
# Never import Python modules from the SSH caller's writable working directory.
cd "$TOOLS"
[[ "$ARCHIVE" =~ ^/var/lib/certificate-manager-ci/incoming/release-[0-9]+-[0-9]+\.tar\.gz$ && "$DIGEST" =~ ^[a-f0-9]{64}$ ]]
[[ -f "$ARCHIVE" && ! -L "$ARCHIVE" && "$(realpath "$ARCHIVE")" == "$ARCHIVE" ]]
[[ "$(stat -c %s "$ARCHIVE")" -le 536870912 ]]
readonly STAGE="$(mktemp -d "$WORK_DIR/release.XXXXXX")"
cleanup() {
    [[ "$STAGE" == "$WORK_DIR"/release.* && -d "$STAGE" && ! -L "$STAGE" ]] && rm -rf -- "$STAGE"
}
trap cleanup EXIT
# Copy to a root-private snapshot before checking or extracting mutable uploaded data.
cp -- "$ARCHIVE" "$STAGE/archive.tar.gz"
printf '%s  %s\n' "$DIGEST" "$STAGE/archive.tar.gz" | sha256sum -c -
"$APP_DIR/.venv/bin/python" -I "$TOOLS/safe-extract.py" "$STAGE/archive.tar.gz" "$STAGE/release"
if [[ -f "$STAGE/release/server-release.json" && ! -e "$STAGE/release/release.json" ]]; then
    "$APP_DIR/.venv/bin/python" -I "$TOOLS/verify-server-release.py" "$STAGE/release"
    readonly RELEASE_KIND=server
else
    "$APP_DIR/.venv/bin/python" -I "$TOOLS/verify-full-release.py" "$STAGE/release"
    readonly RELEASE_KIND=full
fi

# Never install arbitrary uploaded build hooks as root. Missing/upgraded dependencies need admin preparation.
"$APP_DIR/.venv/bin/python" -I - "$STAGE/release/requirements.txt" <<'PY'
from importlib import metadata
from pathlib import Path
from pip._vendor.packaging.requirements import Requirement
import sys
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    requirement = Requirement(line)
    if requirement.url:
        raise SystemExit('URL dependencies require manual administrator approval.')
    if requirement.marker and not requirement.marker.evaluate():
        continue
    try:
        installed = metadata.version(requirement.name)
    except metadata.PackageNotFoundError:
        raise SystemExit(f'Missing server dependency: {requirement.name}; ask the administrator to prepare it first.')
    if installed not in requirement.specifier:
        raise SystemExit(f'Server dependency upgrade needed: {requirement.name}; prepare it before deploying.')
PY
# Only preinstalled root-owned tools execute as root; uploaded deploy scripts are never executed.
logger -t certificate-manager-ci "Starting deployment: $(basename "$ARCHIVE")"
if [[ "$RELEASE_KIND" == server ]]; then
    bash "$TOOLS/setup-email-reminders-update.sh" "$STAGE/release"
else
    CM_TRUSTED_DEPLOY_TOOLS="$TOOLS" bash "$TOOLS/setup-full-update.sh" "$STAGE/release"
fi
logger -t certificate-manager-ci "Deployment completed: $(basename "$ARCHIVE")"
rm -f -- "$ARCHIVE"
