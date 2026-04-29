#!/bin/bash
# Run ERA SHACL benchmark for maplib using the local wheel (native, no Docker).
# Usage: cd rdf-benchmark && bash run_era_maplib.sh
#
# Prerequisites: pip install maplib-0.20.15-cp310-abi3-macosx_14_0_arm64.whl

set -euo pipefail

ERA_DIR="ERA-SHACL-Benchmark-main"
RESULTS_DIR="$ERA_DIR/results/maplib_v0.20.15"
VALIDATE="$ERA_DIR/engines/maplib/validate.py"
RUNS=6

mkdir -p "$RESULTS_DIR/reports"

for subset in ES FR ERA; do
    for shapeset in core era tds; do
        shape_file="$ERA_DIR/shapes/${shapeset}_shapes.ttl"
        data_file="$ERA_DIR/data/${subset}.ttl"
        csv_file="$RESULTS_DIR/${subset}_${shapeset}_results.csv"

        if [ ! -f "$data_file" ]; then
            echo "SKIP $subset — data file not found: $data_file"
            continue
        fi
        if [ ! -f "$shape_file" ]; then
            echo "SKIP $shapeset — shape file not found: $shape_file"
            continue
        fi

        echo "loading, validation, memory_usage" > "$csv_file"

        for ((i=0; i<RUNS; i++)); do
            echo "-> maplib v0.20.15 | $subset × $shapeset | run $i"

            report_file="$RESULTS_DIR/reports/${subset}_${shapeset}_report.ttl"

            # Run validate.py and capture output
            output=$(python3 "$VALIDATE" "$data_file" "$shape_file" "$report_file" 2>&1)

            loading=$(echo "$output" | grep "Load time:" | awk -F: '{print $2}' | tr -d ' ')
            validation=$(echo "$output" | grep "Validation time:" | awk -F: '{print $2}' | tr -d ' ')

            echo "$loading, $validation, 0" >> "$csv_file"
            echo "   load=${loading}s  val=${validation}s"
        done
    done
done

echo ""
echo "Done! Results in $RESULTS_DIR/"
