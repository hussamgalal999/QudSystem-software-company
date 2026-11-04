#!/bin/sh
set -eu

TOKEN_FILE="${OWNER_TOKEN_FILE:-/data/.owner-token}"
mkdir -p "$(dirname "$TOKEN_FILE")"
chmod 700 "$(dirname "$TOKEN_FILE")" 2>/dev/null || true

if [ -n "${OWNER_TOKEN:-}" ]; then
  umask 077
  printf '%s\n' "$OWNER_TOKEN" > "$TOKEN_FILE.tmp"
  mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"
else
  if [ ! -s "$TOKEN_FILE" ]; then
    umask 077
    node -e "process.stdout.write(require('node:crypto').randomBytes(48).toString('base64url'))" > "$TOKEN_FILE.tmp"
    mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"
  fi
  OWNER_TOKEN="$(cat "$TOKEN_FILE")"
fi

if [ "${OPENDOTS_ENABLE_KEYLESS_MODEL:-false}" = "true" ]; then
  KEY_FILE="${OPENDOTS_MODEL_KEY_FILE:-/run/freellm/server.key}"
  if [ ! -s "$KEY_FILE" ]; then
    echo "Keyless model routing was requested, but the FreeLLM gateway key is unavailable." >&2
    exit 1
  fi
  OPENAI_API_KEY="$(cat "$KEY_FILE")"
  OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://qudron-freellm:4000/v1}"
  OPENAI_MODEL="${OPENAI_MODEL:-auto}"
  export OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL
fi

export OWNER_TOKEN
chmod 600 "$TOKEN_FILE" 2>/dev/null || true
exec node dist/server/server/index.js
