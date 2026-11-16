#!/bin/bash
# Restart the lab server on a clean datastore, then run the load test.
# usage: run_lab.sh <lab dir> <port> <label> [loadtest args...]
# Only touches processes whose command line names THIS port.
set -u
LAB="$1"; PORT="$2"; LABEL="$3"; shift 3
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="${LAB}/../serve-${LABEL}.log"

pkill -f "serve compShapesV1.tar.zst --addr :${PORT}" 2>/dev/null
pkill -f "url http://localhost:${PORT}/query" 2>/dev/null
sleep 2
if lsof -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; then echo "port ${PORT} still busy"; exit 9; fi

cd "$LAB" || exit 1
rm -f .empirica/local/tajriba.json .empirica/local/callBackSessionToken
(EMPIRICA_PORT=${PORT} nohup empirica serve compShapesV1.tar.zst --addr :${PORT} > "$LOG" 2>&1 &)
for i in $(seq 1 40); do
  sed -e 's/\x1b\[[0-9;]*m//g' "$LOG" 2>/dev/null | grep -q "server: started" && break
  sleep 0.5
done
sed -e 's/\x1b\[[0-9;]*m//g' "$LOG" | grep -q "server: started" || { echo "server did not start"; tail -5 "$LOG"; exit 8; }

cd "$HERE" && node --no-warnings --import ./register.mjs loadtest.mjs \
  --root "$LAB" --url "http://localhost:${PORT}/query" --label "$LABEL" "$@"
RC=$?
echo "--- server errors during run ---"
sed -e 's/\x1b\[[0-9;]*m//g' "$LOG" | grep -E "ERR|Error caught" | sort | uniq -c | sort -rn | head -5
exit $RC
