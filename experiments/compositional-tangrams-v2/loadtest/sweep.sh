#!/bin/bash
# usage: sweep.sh <lab> <port> <tag> <speed> <reps> <games...>
S="$(cd "$(dirname "$0")/.." && pwd)"
LAB="$1"; PORT="$2"; TAG="$3"; SPEED="$4"; REPS="$5"; shift 5
for N in "$@"; do
  echo "######## ${TAG} N=${N} speed=${SPEED} reps=${REPS}  $(date +%H:%M:%S)"
  ./run_lab.sh "$LAB" "$PORT" "${TAG}-n${N}" --games "$N" --reps "$REPS" --speed "$SPEED" \
     --rampSec 20 --maxSec 1500 --out "$S/res-${TAG}-n${N}.json" 2>&1 | grep -vE "WRN scopes: missing scope" | tail -32
done
echo "######## sweep done $(date +%H:%M:%S)"
