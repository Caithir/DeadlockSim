#!/bin/bash
# Build the server, start it on a spare port, run the browser smoke test, then stop the server.
set -euo pipefail
cd "$(dirname "$0")/../.."
cargo build --release --quiet
PORT="${PORT:-18080}"
./target/release/deadlock-sim serve --port "$PORT" >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 50); do
  if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null; then break; fi
  sleep 0.1
done
BASE_URL="http://127.0.0.1:$PORT" node tests/e2e/smoke.cjs
