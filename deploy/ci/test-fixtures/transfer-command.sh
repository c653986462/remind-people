#!/usr/bin/env bash
set -euo pipefail
case "$(basename "$0")" in
    timeout)
        while [[ "$1" == --* ]]; do shift; done
        shift
        exec "$@"
        ;;
    sleep) exit 0 ;;
    python3)
        printf '%s\n' 'Direct pull attempted' >> "$TRANSFER_TEST_ROOT/pull.log"
        [[ "${FAIL_PULL:-false}" != true ]]
        ;;
    ssh)
        printf '%s\n' "$*" >> "$TRANSFER_TEST_ROOT/ssh.log"
        [[ "${FAIL_AUTH:-false}" != true ]]
        ;;
    rsync)
        count=0
        [[ ! -f "$TRANSFER_TEST_ROOT/count" ]] || count="$(<"$TRANSFER_TEST_ROOT/count")"
        count=$((count + 1))
        printf '%s\n' "$count" > "$TRANSFER_TEST_ROOT/count"
        printf '%s\n' "$*" >> "$TRANSFER_TEST_ROOT/rsync.log"
        [[ "${FAIL_ALL:-false}" != true && "$count" -ge 2 ]]
        ;;
    *) exit 1 ;;
esac
