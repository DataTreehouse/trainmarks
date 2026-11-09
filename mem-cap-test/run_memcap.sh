#!/usr/bin/env bash
# Run the in-memory maplib workload inside a Docker container with a HARD memory
# cap, to see how it behaves as available RAM shrinks. The kernel OOM-kills the
# container if maplib exceeds the cap; results are saved after every op, so a
# kill still leaves a partial JSON showing how far it got.
#
# Usage:
#   bash run_memcap.sh <cap> [scales]
#   bash run_memcap.sh 4g                      # 4 GB cap, all scales
#   bash run_memcap.sh 2g large,xlarge         # 2 GB cap, only 1M + 10M
#   bash run_memcap.sh 1g xlarge               # 1 GB cap, only 10M
#
# Then compare caps by editing the cap and re-running; each writes a separate
# results/results_maplib_memcap_<cap>.json.
#
# Notes:
#   * Uses the OPEN-SOURCE in-memory maplib (pip) — a Linux container can't run
#     the licensed macOS disk-backed wheel. Version is printed at the top of the log.
#   * --memory-swap is set equal to --memory so it CANNOT spill to swap (a true cap).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

CAP="${1:?usage: run_memcap.sh <cap> [scales]   e.g. run_memcap.sh 2g large,xlarge}"
SCALES="${2:-medium,large,xlarge}"

# Write test output to this folder's own ./results — NEVER the main benchmark
# results/ — so the real bench numbers are never touched.
mkdir -p "$PWD/results"
echo "=== maplib in-memory, HARD cap=$CAP, scales=$SCALES ==="
echo "OOM-kill (exit 137) at this cap means maplib needed more than $CAP for that step."
echo ""

docker run --rm \
  --memory="$CAP" --memory-swap="$CAP" \
  -v "$ROOT/data":/data:ro \
  -v "$ROOT/queries":/queries:ro \
  -v "$PWD":/work:ro \
  -v "$PWD/results":/out \
  python:3.12-slim \
  bash -c "pip install --quiet maplib psutil && python /work/bench_memcap.py '$SCALES' '$CAP'" \
  || echo -e "\n>>> Container exited non-zero (exit 137 = OOM-killed at $CAP). Partial results saved."

echo ""
echo "Results: mem-cap-test/results/results_maplib_memcap_$CAP.json"
