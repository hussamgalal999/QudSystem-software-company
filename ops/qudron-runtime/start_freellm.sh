#!/bin/sh
set -eu
STATE_DIR="${FREELM_STATE_DIR:-/home/freelm/.cache/freelm}"
mkdir -p "$STATE_DIR"
chmod 750 "$STATE_DIR" 2>/dev/null || true
KEY_FILE="$STATE_DIR/server.key"

if [ -n "${FREELM_SERVER_KEY:-}" ]; then
  umask 077
  printf '%s\n' "$FREELM_SERVER_KEY" > "$KEY_FILE"
else
  if [ ! -s "$KEY_FILE" ]; then
    umask 077
    python -c 'import secrets; print(secrets.token_urlsafe(48))' > "$KEY_FILE.tmp"
    mv "$KEY_FILE.tmp" "$KEY_FILE"
  fi
  FREELM_SERVER_KEY="$(cat "$KEY_FILE")"
fi
export FREELM_SERVER_KEY
chgrp 10001 "$KEY_FILE" 2>/dev/null || true
chmod 640 "$KEY_FILE" 2>/dev/null || true
exec freelm serve --host 0.0.0.0 --port 4000 --quiet
