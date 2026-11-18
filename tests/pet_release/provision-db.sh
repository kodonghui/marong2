#!/usr/bin/env bash
set -euo pipefail
umask 077
export LC_ALL=C
export PGCONNECT_TIMEOUT=4

root=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
pg=/usr/lib/postgresql/16/bin
trial=$(mktemp -d /var/tmp/marong-pet-provision-test.XXXXXXXX)
cluster=$trial/data
socket=$trial/socket
mkdir -m 0700 "$socket"
cleanup() {
    if [[ -f $cluster/postmaster.pid ]]; then
        "$pg/pg_ctl" -D "$cluster" -m fast -w stop >/dev/null
    fi
    if [[ $trial == /var/tmp/marong-pet-provision-test.* && $(realpath -- "$trial") == "$trial" && -O $trial ]]; then
        rm -rf -- "$trial"
    fi
}
trap cleanup EXIT
port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
operator=$(id -un)
printf '%s\n' "$(openssl rand -hex 32)" > "$trial/operator-password"
"$pg/initdb" -D "$cluster" --no-locale -U "$operator" --auth-local=peer --auth-host=scram-sha-256 \
    --pwfile="$trial/operator-password" >/dev/null
printf 'qa_pet_identity %s marong_pet\n' "$operator" >> "$cluster/pg_ident.conf"
sed '/^[[:space:]]*local[[:space:]].*[[:space:]]peer$/s/$/ map=qa_pet_identity/' \
    "$root/deploy/pet/marong-pet.pg_hba.conf" > "$cluster/pet.conf"
{
    printf 'include "pet.conf"\n'
    cat "$cluster/pg_hba.conf"
} > "$cluster/with-include.conf"
mv -- "$cluster/with-include.conf" "$cluster/pg_hba.conf"
"$pg/pg_ctl" -D "$cluster" -o "-p $port -k $socket -h 127.0.0.1" -l "$trial/postgres.log" -w start >/dev/null

export PGHOST="$socket" PGPORT="$port" PGUSER="$operator" PGDATABASE=postgres
sql() { "$pg/psql" -X -w -v ON_ERROR_STOP=1 -A -t "$@"; }
provision="$root/deploy/pet/provision-db.sql"
sql -c 'CREATE DATABASE marong' >/dev/null
baseline=$(sql -c "SELECT COALESCE(datacl,acldefault('d',datdba))::text FROM pg_database WHERE datname='marong'")
test "$(sql -c 'SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL')" = 0

if sql -d marong -f "$provision" > "$trial/run.log" 2>&1; then exit 1; fi
grep -F -q 'while connected to postgres' "$trial/run.log"
test "$(sql -c "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'marong_pet%'")" = 0
printf 'WRONG_DATABASE_REJECTED=PASS\n'

sql -c 'CREATE ROLE marong_pet LOGIN CREATEDB' >/dev/null
if sql -f "$provision" > "$trial/run.log" 2>&1; then exit 1; fi
grep -F -q 'existing pet roles' "$trial/run.log"
test "$(sql -c "SELECT count(*) FROM pg_database WHERE datname='marong_pet'")" = 0
sql -c 'ALTER ROLE marong_pet NOCREATEDB' >/dev/null
printf 'UNEXPECTED_ROLE_REJECTED=PASS\n'

sql -f "$provision" > "$trial/run.log" 2>&1 || { tail -20 "$trial/run.log" >&2; exit 1; }
printf 'NEW_DATABASE_CREATED=PASS\n'
sql -c 'ALTER DATABASE marong_pet OWNER TO CURRENT_USER' >/dev/null
if sql -f "$provision" > "$trial/run.log" 2>&1; then exit 1; fi
grep -F -q 'unexpected owner' "$trial/run.log"
test "$(sql -d marong_pet -c "SELECT count(*) FROM pg_tables WHERE schemaname='pet'")" = 24
sql -c 'ALTER DATABASE marong_pet OWNER TO marong_pet_owner' >/dev/null
printf 'UNEXPECTED_DATABASE_OWNER_REJECTED=PASS\n'

for _ in 1 2; do sql -f "$provision" > "$trial/run.log" 2>&1 || { tail -20 "$trial/run.log" >&2; exit 1; }; done
test "$(sql -U marong_pet -d marong_pet -c "SELECT count(*) FROM pg_tables WHERE schemaname='pet'")" = 24
test "$baseline" = "$(sql -c "SELECT COALESCE(datacl,acldefault('d',datdba))::text FROM pg_database WHERE datname='marong'")"
test "$(sql -d marong -c 'SELECT current_database()')" = marong
test "$(sql -d marong_pet -c "SELECT COALESCE((SELECT value FROM pet.settings WHERE key='payments_enabled'), 'false'::jsonb)")" = false
printf 'IDEMPOTENT_SCHEMA_TABLES=24\nPAYMENTS_DISABLED=PASS\nLEGACY_DB_UNCHANGED=PASS\n'

for transport in "$socket" 127.0.0.1; do
    if sql -h "$transport" -U marong_pet -d marong -c 'SELECT 1' > "$trial/run.log" 2>&1; then exit 1; fi
    grep -F -q 'pg_hba.conf rejects connection' "$trial/run.log"
done
printf 'LEGACY_CONNECTIONS_DENIED=2\n'
