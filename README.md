# RDF Framework Benchmark

A reproducible benchmark comparing five RDF frameworks on I/O performance (read/write Turtle and N-Triples) and SPARQL query performance across three dataset scales.

**Frameworks tested:** maplib (Python/Rust), oxigraph (Python/Rust), rdflib (Python), Apache Jena (Java), Eclipse RDF4J (Java)

**Results:** Open `benchmark.html` in a browser to view the interactive report with charts, framework filters, and expandable query details.

## Prerequisites

**Python frameworks:**
- Python 3.10+
- `pip install maplib pyoxigraph rdflib`

**Java frameworks:**
- Java 11+
- Maven 3.8+

## Directory structure

```
rdf-benchmark/
├── BENCHMARK.md          ← you are here
├── benchmark.html        ← interactive results report
├── generate_data.py      ← synthetic data generator
├── data/                 ← generated .ttl and .nt files
├── queries/              ← SPARQL query files (q1–q4)
├── results/              ← JSON output from each framework
├── python-maplib/        ← maplib benchmark script
├── python-oxigraph/      ← oxigraph benchmark script
├── python-rdflib/        ← rdflib benchmark script
├── java-jena/            ← Jena benchmark (Maven project)
└── java-rdf4j/           ← RDF4J benchmark (Maven project)
```

## Step 1: Generate test data

From the `rdf-benchmark/` root directory:

```bash
python generate_data.py
```

This creates Turtle (`.ttl`) and N-Triples (`.nt`) files in `data/` at three scales, plus four SPARQL query files in `queries/`:

| Scale   | Triples | Turtle size | N-Triples size |
|---------|---------|-------------|----------------|
| Medium  | ~100K   | ~3.6 MB     | ~10.9 MB       |
| Large   | ~1M     | ~36.9 MB    | ~111 MB        |
| Xlarge  | ~10M    | ~369 MB     | ~1.1 GB        |

The data models a synthetic e-commerce graph with customers, orders, and products. A fixed random seed (`42`) ensures reproducibility.

## Step 2: Run Python benchmarks

Each Python script runs from its own directory and writes results to `../results/`.

```bash
# maplib
cd python-maplib
python bench_maplib.py
cd ..

# oxigraph
cd python-oxigraph
python bench_oxigraph.py
cd ..

# rdflib (this one is slow — ~5 min on medium, much longer on xlarge)
cd python-rdflib
python bench_rdflib.py
cd ..
```

Each script benchmarks read/write for Turtle and N-Triples, then runs four SPARQL queries (best of 3 after warmup). A 5-minute timeout protects against hangs on large datasets.

## Step 3: Run Java benchmarks

The Java benchmarks are Maven projects. Build and run from each directory:

```bash
# Apache Jena
cd java-jena
mvn package -q
java -jar target/jena-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results
cd ..

# Eclipse RDF4J
cd java-rdf4j
mvn package -q
java -jar target/rdf4j-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results
cd ..
```

The JVM is warmed up with a full medium-dataset read before timing begins.

## Step 4: View results

Open `benchmark.html` in any browser. The report includes:

- **I/O performance charts** — grouped bar charts for read/write at each scale
- **Query performance charts** — SPARQL timing comparisons
- **Scale tabs** — switch between 100K, 1M, and 10M triple datasets
- **Log scale toggle** — useful when comparing frameworks with very different speeds
- **Framework filters** — click chips to show/hide individual frameworks
- **Expandable query rows** — click any query name to see the full SPARQL

## SPARQL queries

| ID | Description | Complexity |
|----|-------------|------------|
| Q1 | `COUNT` all triples | Full scan |
| Q2 | Top 20 customers by spend (`GROUP BY` + `SUM` + `ORDER BY`) | Aggregation over joins |
| Q3 | 3-entity join (customer + order + product) with country filter | Multi-pattern + filter |
| Q4 | Revenue by country/segment with `OPTIONAL` orders | OPTIONAL + aggregation |

## Methodology

All frameworks use the same data files and SPARQL queries.

**Timing:** Python uses `time.perf_counter()` with garbage collection between runs. Java uses `System.nanoTime()` with JVM warmup.

**Queries:** Best of 3 runs after a warmup run.

**I/O:** Single timed run (no averaging), since allocation overhead is part of real-world cost.

## Notes

- The xlarge dataset (~10M triples) requires significant memory. Expect 4+ GB for in-memory frameworks.
- rdflib is pure Python and will be substantially slower than the Rust-backed and Java frameworks — this is expected and part of what the benchmark illustrates.
- maplib reads use `parallel=True` for multi-threaded parsing; oxigraph uses its default bulk loader.
