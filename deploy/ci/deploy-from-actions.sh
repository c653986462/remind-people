#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for name in DEPLOY_HOST DEPLOY_USER DEPLOY_SSH_KEY DEPLOY_KNOWN_HOSTS GITHUB_RUN_ID GITHUB_RUN_ATTEMPT; do
    [[ -n "${!name:-}" ]] || { printf 'Missing GitHub Actions setting: %s\n' "$name" >&2; exit 1; }
done
[[ "$DEPLOY_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ && "$DEPLOY_USER" == certmgr-deploy ]]
readonly SSH_PORT="${DEPLOY_PORT:-22}"
[[ "$SSH_PORT" =~ ^[0-9]+$ && "$SSH_PORT" -ge 1 && "$SSH_PORT" -le 65535 ]]
[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ && "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]
cd release-artifact
readonly DEPLOY_KIND="${DEPLOY_KIND:-server}"
[[ "$DEPLOY_KIND" == server || "$DEPLOY_KIND" == desktop ]]
if [[ "$DEPLOY_KIND" == server ]]; then
    archives=(certificate-manager-server-*.tar.gz)
    transfer_seconds=180
    archive_suffix=1
else
    archives=(certificate-manager-full-*.tar.gz)
    transfer_seconds=4200
    archive_suffix=2
fi
present=()
for candidate in "${archives[@]}"; do [[ -f "$candidate" ]] && present+=("$candidate"); done
[[ ${#present[@]} -eq 1 ]] || { echo "Expected exactly one $DEPLOY_KIND release archive." >&2; exit 1; }
readonly ARCHIVE="${present[0]}"
sha256sum -c "$ARCHIVE.sha256"
readonly DIGEST="$(sha256sum "$ARCHIVE" | cut -d ' ' -f 1)"
# Keep the same remote path when rerunning a failed job so rsync can resume a partial EXE upload.
readonly REMOTE_ARCHIVE="/var/lib/certificate-manager-ci/incoming/release-$GITHUB_RUN_ID-$archive_suffix.tar.gz"
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
readonly RSYNC_SSH="ssh -p $SSH_PORT -i $SSH_DIR/key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$SSH_DIR/known_hosts -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3"
printf 'Checking SSH authentication and pinned host key...\n'
timeout --signal=TERM --kill-after=10s 45s ssh "${ssh_options[@]}" -p "$SSH_PORT" "$TARGET" true
printf 'SSH verified. Uploading %s package (%s bytes); each failed transfer resumes the same remote file.\n' "$DEPLOY_KIND" "$(stat -c %s "$ARCHIVE")"
uploaded=false
if [[ "$DEPLOY_KIND" == desktop && -n "${GH_ARTIFACT_TOKEN:-}" ]]; then
    printf 'Trying bounded parallel HTTPS artifact pull on the server (no API token sent to server)...\n'
    for pull_attempt in 1 2 3; do
        printf 'Direct pull attempt %s/3; completed/partial ranges are retained for resume.\n' "$pull_attempt"
        if timeout --signal=TERM --kill-after=10s 600s python3 "$SCRIPT_DIR/pull-artifact.py" "$ARCHIVE" "$DIGEST" "$REMOTE_ARCHIVE" ssh "${ssh_options[@]}" -p "$SSH_PORT" "$TARGET"; then
            uploaded=true
            break
        fi
    done
    if [[ "$uploaded" != true ]]; then
        printf 'Direct pull unavailable; falling back to the same resumable SSH upload.\n'
    fi
fi
unset GH_ARTIFACT_TOKEN
for attempt in 1 2 3; do
    [[ "$uploaded" != true ]] || break
    printf 'Upload attempt %s/3; transfer budget %s seconds.\n' "$attempt" "$transfer_seconds"
    if timeout --signal=TERM --kill-after=30s "${transfer_seconds}s" rsync --timeout=120 --partial --append-verify --no-compress --info=progress2 -e "$RSYNC_SSH" "$ARCHIVE" "$TARGET:$REMOTE_ARCHIVE"; then
        uploaded=true
        break
    fi
    if [[ "$attempt" -lt 3 ]]; then
        printf 'Transfer interrupted or timed out; retrying with verified resume.\n'
        sleep 5
    fi
done
[[ "$uploaded" == true ]] || { echo 'Upload failed after three attempts; no server publication was requested. Re-run this job to resume the same artifact.' >&2; exit 1; }
printf 'Upload complete. Starting trusted %s publication...\n' "$DEPLOY_KIND"
mode_argument=''
if [[ "$DEPLOY_KIND" == desktop ]]; then mode_argument=' desktop'; fi
timeout --signal=TERM --kill-after=30s 600s ssh "${ssh_options[@]}" -p "$SSH_PORT" "$TARGET" "sudo -n /usr/local/sbin/certificate-manager-ci-deploy '$REMOTE_ARCHIVE' '$DIGEST'$mode_argument"
