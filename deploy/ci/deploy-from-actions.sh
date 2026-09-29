#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
for name in DEPLOY_HOST DEPLOY_USER DEPLOY_SSH_KEY DEPLOY_KNOWN_HOSTS EXPECTED_VERSION GITHUB_RUN_ID GITHUB_RUN_ATTEMPT; do
    [[ -n "${!name:-}" ]] || { printf 'Missing GitHub Actions setting: %s\n' "$name" >&2; exit 1; }
done
[[ "$DEPLOY_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ && "$DEPLOY_USER" == certmgr-deploy ]]
readonly SSH_PORT="${DEPLOY_PORT:-22}"
[[ "$SSH_PORT" =~ ^[0-9]+$ && "$SSH_PORT" -ge 1 && "$SSH_PORT" -le 65535 ]]
[[ "$EXPECTED_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$GITHUB_RUN_ID" =~ ^[0-9]+$ && "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]
readonly ARCHIVE="certificate-manager-full-$EXPECTED_VERSION.tar.gz"
cd release-artifact
sha256sum -c "$ARCHIVE.sha256"
readonly DIGEST="$(sha256sum "$ARCHIVE" | cut -d ' ' -f 1)"
readonly REMOTE_ARCHIVE="/var/lib/certificate-manager-ci/incoming/release-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT.tar.gz"
readonly SSH_DIR="$(mktemp -d "$RUNNER_TEMP/certificate-manager-ssh.XXXXXX")"
cleanup() {
    [[ "$SSH_DIR" == "$RUNNER_TEMP"/certificate-manager-ssh.* && -d "$SSH_DIR" && ! -L "$SSH_DIR" ]] && rm -rf -- "$SSH_DIR"
}
trap cleanup EXIT
printf '%s\n' "$DEPLOY_SSH_KEY" > "$SSH_DIR/key"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > "$SSH_DIR/known_hosts"
unset DEPLOY_SSH_KEY DEPLOY_KNOWN_HOSTS
readonly TARGET="$DEPLOY_USER@$DEPLOY_HOST"
ssh_options=(-i "$SSH_DIR/key" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$SSH_DIR/known_hosts" -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3)
scp "${ssh_options[@]}" -P "$SSH_PORT" "$ARCHIVE" "$TARGET:$REMOTE_ARCHIVE"
ssh "${ssh_options[@]}" -p "$SSH_PORT" "$TARGET" "sudo -n /usr/local/sbin/certificate-manager-ci-deploy '$REMOTE_ARCHIVE' '$DIGEST'"
