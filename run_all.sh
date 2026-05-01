#!/bin/bash
# Run all RDF benchmarks sequentially.
# Continues past failures — reports which ones failed at the end.
# Usage: cd rdf-benchmark && bash run_all.sh

ROOT="$(cd "$(dirname "$0")" && pwd)"
FAILED=""
SKIPPED=""

run_bench() {
    local num="$1" name="$2" cmd="$3"
    echo ""
    echo "──────────────────────────────────────"
    echo "$num  $name"
    echo "──────────────────────────────────────"
    if eval "$cmd"; then
        echo "  ✓ $name done"
    else
        echo "  ✗ $name FAILED (exit code $?)"
        FAILED="$FAILED  - $name\n"
    fi
}

echo "=== RDF Benchmark Suite ==="
echo "Root: $ROOT"

# Python frameworks
run_bench "1/11" "maplib" \
    "cd '$ROOT/python-maplib' && python bench_maplib.py"

run_bench "2/11" "maplib (disk)" \
    "cd '$ROOT/python-maplib-disk' && python bench_maplib_disk.py"

run_bench "3/11" "oxigraph" \
    "cd '$ROOT/python-oxigraph' && python bench_oxigraph.py"

run_bench "4/11" "rdflib (slow)" \
    "cd '$ROOT/python-rdflib' && python bench_rdflib.py"

# Java frameworks
if command -v mvn &> /dev/null; then
    run_bench "5/11" "Apache Jena" \
        "cd '$ROOT/java-jena' && mvn package -q -DskipTests 2>/dev/null && java -jar target/jena-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results"

    run_bench "6/11" "Eclipse RDF4J" \
        "cd '$ROOT/java-rdf4j' && mvn package -q -DskipTests 2>/dev/null && java -jar target/rdf4j-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results"
else
    SKIPPED="$SKIPPED  - Jena, RDF4J (mvn not found)\n"
fi

# Docker frameworks
if command -v docker &> /dev/null; then
    run_bench "7/11" "QLever (Docker)" \
        "cd '$ROOT/qlever' && python bench_qlever.py"

    run_bench "8/11" "Virtuoso (Docker)" \
        "cd '$ROOT/virtuoso' && python bench_virtuoso.py"

    run_bench "9/11" "GraphDB (Docker)" \
        "cd '$ROOT/graphdb' && python bench_graphdb.py"

    run_bench "10/11" "dotNetRDF (Docker)" \
        "cd '$ROOT/dotnetrdf' && python bench_dotnetrdf.py"

    run_bench "11/11" "Neo4j + n10s (Docker)" \
        "cd '$ROOT/neo4j' && python bench_neo4j.py"
else
    SKIPPED="$SKIPPED  - QLever, Virtuoso, GraphDB, dotNetRDF, Neo4j (docker not found)\n"
fi

# Summary
echo ""
echo "========================================="
echo "=== Summary ==="
echo "========================================="
ls -lh "$ROOT/results/"*.json 2>/dev/null
if [ -n "$SKIPPED" ]; then
    echo ""
    echo "Skipped:"
    echo -e "$SKIPPED"
fi
if [ -n "$FAILED" ]; then
    echo "Failed:"
    echo -e "$FAILED"
else
    echo ""
    echo "All benchmarks completed successfully."
fi
