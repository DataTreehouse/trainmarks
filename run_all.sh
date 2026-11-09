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

# ── Pre-flight: fail early, and record exactly which versions this run uses ──
mkdir -p "$ROOT/results"
JAVA_MAJOR=$(java -version 2>&1 | head -1 | sed -E 's/.*version "([0-9]+).*/\1/')
if [ -n "$JAVA_MAJOR" ] && [ "$JAVA_MAJOR" -lt 25 ] 2>/dev/null; then
    echo "!! Java $JAVA_MAJOR found — RDF4J 6.x needs Java 25+. Aborting."; exit 1
fi
if command -v docker &> /dev/null && ! docker info &> /dev/null; then
    echo "!! docker is installed but the daemon is not running — start Docker Desktop first. Aborting."; exit 1
fi
MAPLIB_VERSION=$(cd "$ROOT/python-maplib" && uv run python -c 'import importlib.metadata as m; print(m.version("maplib"))' 2>/dev/null || echo "NOT FOUND")
{
    echo "run started: $(date -u +%FT%TZ)  host: $(uname -sm)"
    echo "maplib:      $MAPLIB_VERSION   (from the default interpreter uv resolves)"
    echo "pyoxigraph:  0.5.13   pyrudof: 0.3.38   rdflib: 7.6.0"
    echo "jena:        $(grep -oE '<jena.version>[^<]+' "$ROOT/java-jena/pom.xml" | cut -d'>' -f2)   rdf4j: $(grep -oE '<rdf4j.version>[^<]+' "$ROOT/java-rdf4j/pom.xml" | cut -d'>' -f2)"
    echo "java:        $(java -version 2>&1 | head -1)"
    echo "dotNetRDF:   $(grep -oE 'dotNetRdf" Version="[^"]+' "$ROOT/dotnetrdf/BenchDotNetRdf.csproj" | cut -d'"' -f3) on $(grep -oE 'dotnet/sdk:[0-9.]+' "$ROOT/dotnetrdf/bench_dotnetrdf.py")"
    grep -hE '^[A-Z0-9_]+_(IMAGE|VERSION) = ' "$ROOT"/qlever/bench_qlever.py "$ROOT"/virtuoso/bench_virtuoso.py \
        "$ROOT"/graphdb/bench_graphdb.py "$ROOT"/neo4j/bench_neo4j.py "$ROOT"/tentris/bench_tentris.py
} | tee "$ROOT/results/versions.txt"

# Python frameworks
run_bench "1/13" "maplib" \
    "cd '$ROOT/python-maplib' && uv run --with psutil bench_maplib.py"

run_bench "2/13" "maplib (disk)" \
    "cd '$ROOT/python-maplib-disk' && uv run --with psutil bench_maplib_disk.py"

run_bench "3/13" "oxigraph" \
    "cd '$ROOT/python-oxigraph' && uv run --with pyoxigraph==0.5.13 --with psutil bench_oxigraph.py"

run_bench "3b/13" "oxigraph (disk)" \
    "cd '$ROOT/python-oxigraph-disk' && uv run --with pyoxigraph==0.5.13 --with psutil bench_oxigraph_disk.py"

run_bench "4/14" "rdflib (slow)" \
    "cd '$ROOT/python-rdflib' && uv run --with rdflib==7.6.0 --with psutil bench_rdflib.py"

run_bench "4b/14" "rudof" \
    "cd '$ROOT/python-rudof' && uv run --with pyrudof==0.3.38 --with psutil bench_rudof.py"

# Java frameworks
if command -v mvn &> /dev/null; then
    run_bench "5/13" "Apache Jena" \
        "cd '$ROOT/java-jena' && mvn package -q -DskipTests 2>/dev/null && java -jar target/jena-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results"

    run_bench "6/13" "Eclipse RDF4J" \
        "cd '$ROOT/java-rdf4j' && mvn package -q -DskipTests 2>/dev/null && java -jar target/rdf4j-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results"
else
    SKIPPED="$SKIPPED  - Jena, RDF4J (mvn not found)\n"
fi

# Docker frameworks
if command -v docker &> /dev/null; then
    run_bench "7/13" "QLever (Docker)" \
        "cd '$ROOT/qlever' && uv run bench_qlever.py"

    run_bench "8/13" "Virtuoso (Docker)" \
        "cd '$ROOT/virtuoso' && uv run bench_virtuoso.py"

    run_bench "9/13" "GraphDB (Docker)" \
        "cd '$ROOT/graphdb' && uv run bench_graphdb.py"

    run_bench "10/13" "dotNetRDF (Docker)" \
        "cd '$ROOT/dotnetrdf' && uv run bench_dotnetrdf.py"

    run_bench "11/13" "Neo4j + n10s (Docker)" \
        "cd '$ROOT/neo4j' && uv run bench_neo4j.py"

    run_bench "12/13" "TentrisDB (Docker)" \
        "cd '$ROOT/tentris' && uv run bench_tentris.py"
else
    SKIPPED="$SKIPPED  - QLever, Virtuoso, GraphDB, dotNetRDF, Neo4j, TentrisDB (docker not found)\n"
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
