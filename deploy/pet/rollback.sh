#!/usr/bin/env bash
set -euo pipefail

if [[ $# == 1 && $1 == --dry-run ]]; then
    printf '%s\n' \
        'Stop and disable: marong-pet-call.service marong-pet.service' \
        'Withdraw the configured pet hostname using the colocated remove-pet-hostname.sh' \
        'Retain the pet database, media and database access rules'
    exit 0
fi
if [[ $# != 0 ]]; then
    printf '%s\n' 'usage: rollback.sh [--dry-run]' >&2
    exit 2
fi

rollback_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
withdraw="$rollback_dir/remove-pet-hostname.sh"
status=0
systemctl disable --now marong-pet-call.service marong-pet.service || status=1
if [[ ! -x $withdraw ]]; then
    printf '%s\n' 'The pet hostname withdrawal command is missing' >&2
    status=1
else
    "$withdraw" || status=1
fi
exit "$status"
