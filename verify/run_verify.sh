#!/bin/bash
# Result-equivalence check for the Trainmarks queries.
# Loads the same data into every engine (the same way the bench scripts do), runs Q1–Q5 once,
# runs Q6 once on a fresh load and dumps the resulting prices, then compares everything.
#
# usage:  cd rdf-benchmark && bash verify/run_verify.sh [medium|large|xlarge] [engines...]
# output: verify/out/<engine>/<scale>/q*.json (canonical), verify/raw/... (engine-native dumps),
#         verify/report_<scale>.txt
set -u
V="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$V")"; cd "$V"
S="${1:-medium}"; shift || true
ENGINES="${*:-maplib oxigraph oxigraph_disk rudof rdflib jena rdf4j dotnetrdf qlever graphdb tentris virtuoso neo4j neo4j_fixed}"
PY="uv run --with maplib --with pyoxigraph==0.5.13 --with pyrudof==0.3.38 --with rdflib==7.6.0 --with psutil python"

for e in $ENGINES; do
  echo "── $e ($S)"
  case $e in
    maplib|oxigraph|oxigraph_disk|rudof|rdflib)
      $PY run_py.py $e $S out ;;
    jena)
      mkdir -p build/jena && javac -cp "$ROOT/java-jena/target/jena-benchmark-1.0-SNAPSHOT.jar" -d build/jena java/JenaVerify.java &&
      java -Xmx8g -cp "$ROOT/java-jena/target/jena-benchmark-1.0-SNAPSHOT.jar:build/jena" benchmark.JenaVerify \
        "$ROOT/data/$S.ttl" "$ROOT/queries" raw/jena/$S q6_check.rq
      $PY ingest_raw.py jena $S raw/jena/$S out > /dev/null ;;
    rdf4j)
      mkdir -p build/rdf4j && javac -cp "$ROOT/java-rdf4j/target/rdf4j-benchmark-1.0-SNAPSHOT.jar" -d build/rdf4j java/RDF4JVerify.java &&
      java -Xmx8g -cp "$ROOT/java-rdf4j/target/rdf4j-benchmark-1.0-SNAPSHOT.jar:build/rdf4j" benchmark.RDF4JVerify \
        "$ROOT/data/$S.ttl" "$ROOT/queries" raw/rdf4j/$S q6_check.rq
      $PY ingest_raw.py rdf4j $S raw/rdf4j/$S out > /dev/null ;;
    dotnetrdf)
      docker build -q -t verify-dotnetrdf dotnet > /dev/null &&
      docker run --rm -v "$ROOT":/rb -v "$V":/v verify-dotnetrdf /rb/data/$S.nt /rb/queries /v/raw/dotnetrdf/$S /v/q6_check.rq
      $PY ingest_raw.py dotnetrdf $S raw/dotnetrdf/$S out > /dev/null ;;
    qlever|graphdb|tentris|virtuoso|neo4j)
      rm -rf raw/$e/$S; $PY run_server.py $e $S raw/$e/$S
      $PY ingest_raw.py $e $S raw/$e/$S out > /dev/null ;;
    neo4j_fixed)   # proposed corrected Cypher (verify/neo4j_fixed.py) against the same n10s import
      rm -rf raw/neo4j_fixed/$S; NEO4J_FIXED=1 $PY run_server.py neo4j $S raw/neo4j_fixed/$S
      $PY ingest_raw.py neo4j_fixed $S raw/neo4j_fixed/$S out > /dev/null
      python3 fix_neo4j_iris.py out/neo4j_fixed/$S/q4_optional_aggregation.json ;;
  esac
done
$PY compare.py out $S | tee report_$S.txt
