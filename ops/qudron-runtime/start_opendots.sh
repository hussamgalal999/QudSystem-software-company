#!/bin/sh
set -eu

DATA_DIR="${OPENDOTS_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

ensure_secret() {
  name="$1"
  value="$2"
  path="$3"
  if [ -n "$value" ]; then
    umask 077
    printf '%s\n' "$value" > "$path"
  elif [ ! -s "$path" ]; then
    umask 077
    node -e 'process.stdout.write(require("node:crypto").randomBytes(48).toString("base64url") + "\\n")' > "$path.tmp"
    mv "$path.tmp" "$path"
  fi
  chmod 600 "$path" 2>/dev/null || true
}

OWNER_FILE="${OWNER_TOKEN_FILE:-$DATA_DIR/owner_token}"
if [ -n "${OWNER_TOKEN:-}" ]; then
  ensure_secret OWNER_TOKEN "$OWNER_TOKEN" "$OWNER_FILE"
else
  ensure_secret OWNER_TOKEN "" "$OWNER_FILE"
fi
export OWNER_TOKEN="$(cat "$OWNER_FILE")"

exec node dist/server/server/index.js
