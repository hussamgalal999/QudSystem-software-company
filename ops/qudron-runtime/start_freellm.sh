#!/bin/sh
set -eu
: "${FREELM_SERVER_KEY:?Set FREELM_SERVER_KEY in .env before enabling the free-ai profile}"
exec freelm serve --host 0.0.0.0 --port 4000 --quiet
