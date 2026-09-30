#!/usr/bin/env bash
set -euo pipefail
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_ROOT="$(mktemp -d /tmp/certmgr-transfer-tests.XXXXXX)"
cleanup() {
    [[ "$TEST_ROOT" == /tmp/certmgr-transfer-tests.* && -d "$TEST_ROOT" && ! -L "$TEST_ROOT" && "$(realpath "$TEST_ROOT")" == "$TEST_ROOT" ]] && rm -rf -- "$TEST_ROOT"
}
trap cleanup EXIT
mkdir "$TEST_ROOT/bin" "$TEST_ROOT/release-artifact" "$TEST_ROOT/runtime"
for name in timeout sleep ssh rsync; do
    cp "$SCRIPT_DIR/test-fixtures/transfer-command.sh" "$TEST_ROOT/bin/$name"
    chmod +x "$TEST_ROOT/bin/$name"
done
for kind in server full; do
    printf 'test artifact\n' > "$TEST_ROOT/release-artifact/certificate-manager-$kind-100.tar.gz"
    (cd "$TEST_ROOT/release-artifact"; sha256sum "certificate-manager-$kind-100.tar.gz" > "certificate-manager-$kind-100.tar.gz.sha256")
done
export PATH="$TEST_ROOT/bin:$PATH" RUNNER_TEMP="$TEST_ROOT/runtime" TRANSFER_TEST_ROOT="$TEST_ROOT"
export DEPLOY_HOST=127.0.0.1 DEPLOY_USER=certmgr-deploy DEPLOY_SSH_KEY=test-key DEPLOY_KNOWN_HOSTS=test-host
export GITHUB_RUN_ID=100 GITHUB_RUN_ATTEMPT=1
cd "$TEST_ROOT"
DEPLOY_KIND=server bash "$SCRIPT_DIR/deploy-from-actions.sh"
[[ "$(<"$TEST_ROOT/count")" == 2 ]]
grep -q -- '--append-verify' "$TEST_ROOT/rsync.log"
grep -q 'incoming/release-100-1.tar.gz' "$TEST_ROOT/rsync.log"
grep -q 'sudo -n /usr/local/sbin/certificate-manager-ci-deploy' "$TEST_ROOT/ssh.log"
[[ -z "$(find "$TEST_ROOT/runtime" -mindepth 1 -print -quit)" ]]
rm -f "$TEST_ROOT/count" "$TEST_ROOT/ssh.log" "$TEST_ROOT/rsync.log"
DEPLOY_KIND=desktop bash "$SCRIPT_DIR/deploy-from-actions.sh"
[[ "$(<"$TEST_ROOT/count")" == 2 ]]
grep -q 'incoming/release-100-2.tar.gz' "$TEST_ROOT/rsync.log"
grep -q " desktop$" "$TEST_ROOT/ssh.log"
rm -f "$TEST_ROOT/count" "$TEST_ROOT/ssh.log" "$TEST_ROOT/rsync.log"
if FAIL_ALL=true DEPLOY_KIND=desktop bash "$SCRIPT_DIR/deploy-from-actions.sh"; then echo 'Failure unexpectedly published' >&2; exit 1; fi
[[ "$(<"$TEST_ROOT/count")" == 3 ]]
if grep -q 'sudo -n' "$TEST_ROOT/ssh.log"; then echo 'Incomplete upload invoked publisher' >&2; exit 1; fi
rm -f "$TEST_ROOT/count" "$TEST_ROOT/ssh.log" "$TEST_ROOT/rsync.log"
if FAIL_AUTH=true DEPLOY_KIND=server bash "$SCRIPT_DIR/deploy-from-actions.sh"; then echo 'Bad authentication unexpectedly succeeded' >&2; exit 1; fi
[[ ! -e "$TEST_ROOT/rsync.log" ]]
[[ -z "$(find "$TEST_ROOT/runtime" -mindepth 1 -print -quit)" ]]
echo 'Transfer retry, resume paths, preflight authentication and no-publication-on-failure checks passed.'
