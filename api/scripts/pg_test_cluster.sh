#!/usr/bin/env bash
# Throwaway local Postgres 16 for the `pg` tests (api/tests/pg). Never Neon, never port 5432.
#
#   scripts/pg_test_cluster.sh start   # initdb (first time) and start; safe to repeat
#   scripts/pg_test_cluster.sh url     # print the TEST_DATABASE_URL to export
#   scripts/pg_test_cluster.sh stop    # stop the cluster and delete its data directory
#
# Then:
#   export TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url)
#   .venv/bin/python -m pytest -q -m "not pg"   # the SQLite suite
#   .venv/bin/python -m pytest -q -m pg         # the real Postgres tests
#
# The cluster lives in ${TMPDIR:-/tmp}/wt-pg-test, listens on 127.0.0.1:5544 only (no unix
# socket), trust auth, superuser `postgres`. Each test run makes and drops its own wt_test_* database.
set -euo pipefail
export LC_ALL=en_US.UTF-8  # macOS: postgres refuses to start without a valid locale

PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@16/bin}"
PORT=5544
DIR="${TMPDIR:-/tmp}"
DIR="${DIR%/}/wt-pg-test"
URL="postgresql://postgres@127.0.0.1:${PORT}/postgres"

running() {
  [ -f "$DIR/PG_VERSION" ] && "$PG_BIN/pg_ctl" -D "$DIR/data" status >/dev/null 2>&1
}

case "${1:-}" in
  start)
    if running; then
      echo "already running on 127.0.0.1:${PORT}"
      exit 0
    fi
    mkdir -p "$DIR"
    if [ ! -f "$DIR/data/PG_VERSION" ]; then
      "$PG_BIN/initdb" -D "$DIR/data" -U postgres -A trust --encoding=UTF8 --locale=C >/dev/null
    fi
    "$PG_BIN/pg_ctl" -D "$DIR/data" -l "$DIR/server.log" -w \
      -o "-p ${PORT} -c listen_addresses=127.0.0.1 -c unix_socket_directories= -c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=100" \
      start >/dev/null
    echo "started on 127.0.0.1:${PORT}"
    ;;
  url)
    echo "$URL"
    ;;
  stop)
    if [ -f "$DIR/data/PG_VERSION" ]; then
      "$PG_BIN/pg_ctl" -D "$DIR/data" -m immediate -w stop >/dev/null 2>&1 || true
    fi
    case "$DIR" in
      */wt-pg-test) rm -rf "$DIR" ;;
    esac
    echo "stopped"
    ;;
  *)
    echo "usage: $0 start|stop|url" >&2
    exit 2
    ;;
esac
