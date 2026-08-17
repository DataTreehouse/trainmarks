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
run_bench "1/13" "maplib" \
    "cd '$ROOT/python-maplib' && uv run bench_maplib.py"

run_bench "2/13" "maplib (disk)" \
    "cd '$ROOT/python-maplib-disk' && uv run bench_maplib_disk.py"

run_bench "3/13" "oxigraph" \
    "cd '$ROOT/python-oxigraph' && uv run --with pyoxigraph bench_oxigraph.py"

run_bench "4/13" "rdflib (slow)" \
    "cd '$ROOT/python-rdflib' && uv run --with rdflib bench_rdflib.py"

# Java frameworks
if command -v mvn &> /dev/null; then
    run_bench "5/13" "Apache Jena" \
        "cd '$ROOT/java-jena' && mvn package -q -DskipTests 2>/dev/null && java -jar target/jena-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results"

    run_bench "6/13" "Eclipse RDF4J" \
        "cd '$ROOT/java-rdf4j' && mvn package -q -DskipTests 2>/dev/null && java -jar target/rdf4j-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results"
else
    SKIPPED="$SKIPPED  - Jena, RDF4J (mvn not found)\n"
fi

# QLever (native binary)
if command -v qlever-index &> /dev/null; then
    run_bench "7/13" "QLever (native)" \
        "cd '$ROOT/qlever' && uv run bench_qlever.py"
else
    SKIPPED="$SKIPPED  - QLever (qlever-index not found; brew install qlever)\n"
fi

# Docker frameworks
if command -v docker &> /dev/null; then
    run_bench "8/13" "Virtuoso (Docker)" \
        "cd '$ROOT/virtuoso' && uv run bench_virtuoso.py"

    run_bench "9/13" "GraphDB (Docker)" \
        "cd '$ROOT/graphdb' && uv run bench_graphdb.py"

    run_bench "10/13" "dotNetRDF (Docker)" \
        "cd '$ROOT/dotnetrdf' && uv run bench_dotnetrdf.py"

    run_bench "11/13" "Neo4j + n10s (Docker)" \
        "cd '$ROOT/neo4j' && uv run bench_neo4j.py"

    run_bench "12/13" "Blazegraph (Docker)" \
        "cd '$ROOT/blazegraph' && uv run bench_blazegraph.py"
else
    SKIPPED="$SKIPPED  - Virtuoso, GraphDB, dotNetRDF, Neo4j, Blazegraph (docker not found)\n"
fi

# Node.js frameworks
if command -v node &> /dev/null; then
    run_bench "13/13" "Comunica (Node.js)" \
        "cd '$ROOT/comunica' && uv run bench_comunica.py"
else
    SKIPPED="$SKIPPED  - Comunica (node not found)\n"
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
