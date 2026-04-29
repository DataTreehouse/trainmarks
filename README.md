# RDF Framework Benchmark

A reproducible benchmark comparing twelve RDF frameworks and triplestores on I/O performance (read/write Turtle and N-Triples) and SPARQL query performance across three dataset scales (100K, 1M, and 10M triples).

**Results:** Open `benchmark.html` in a browser to view the interactive report with charts, framework filters, preset groups, and expandable query details.

## Frameworks tested

| Framework | Language | Store type | Version | License |
|-----------|----------|------------|---------|---------|
| maplib | Python (Rust core) | In-memory (Polars + Arrow) | 0.20.15 | Apache 2.0 |
| maplib (disk) | Python (Rust core) | Disk-backed (Polars + Arrow) | 0.20.15 | Proprietary |
| oxigraph | Python (Rust core) | Disk-backed (RocksDB) | 0.5.7 | MIT / Apache 2.0 |
| rdflib | Python (pure) | In-memory (dict-of-dicts) | latest | BSD 3-Clause |
| Apache Jena | Java | In-memory Model | 5.2.0 | Apache 2.0 |
| Eclipse RDF4J | Java | MemoryStore SAIL | 5.0.3 | EDL 1.0 |
| QLever | C++ (Docker) | On-disk index + SPARQL endpoint | latest | Apache 2.0 |
| Kolibrie | Rust | Dictionary-encoded BTreeSet | latest | Proprietary |
| Virtuoso | C (Docker) | Hybrid relational/RDF, column store | 7.x | GPL v2 |
| GraphDB | Java (Docker) | RDF4J-based, on-disk persistence | 10.8.0 | Proprietary (free tier) |
| dotNetRDF | C# (Docker) | In-memory TripleStore | 3.5.1 | MIT |
| Neo4j + n10s | Java (Docker) | Native property graph + RDF import | 5.26 + n10s 5.26.0 | GPL v3 (Community) |

## Prerequisites

**Python frameworks (maplib, maplib-disk, oxigraph, rdflib):**
- Python 3.10+
- `pip install maplib pyoxigraph rdflib`

**Java frameworks (Jena, RDF4J):**
- Java 11+
- Maven 3.8+

**Rust framework (Kolibrie):**
- Rust toolchain (cargo)
- Kolibrie crate (not public — requires access from KU Leuven)

**Docker-based frameworks (QLever, Virtuoso, GraphDB, dotNetRDF, Neo4j):**
- Docker Desktop installed and running
- Images are pulled automatically by each benchmark script, or manually:
  ```bash
  docker pull adfreiburg/qlever
  docker pull openlink/virtuoso-opensource-7:latest
  docker pull ontotext/graphdb:10.8.0
  docker pull mcr.microsoft.com/dotnet/sdk:8.0
  docker pull neo4j:5.26-community
  ```

## Directory structure

```
rdf-benchmark/
├── README.md              ← you are here
├── benchmark.html         ← interactive results report
├── generate_data.py       ← synthetic data generator
├── data/                  ← generated .ttl and .nt files
├── queries/               ← shared SPARQL query files (q1–q4)
├── results/               ← JSON output from each framework
├── python-maplib/         ← maplib benchmark
├── python-maplib-disk/    ← maplib disk-backed benchmark
├── python-oxigraph/       ← oxigraph benchmark
├── python-rdflib/         ← rdflib benchmark
├── java-jena/             ← Jena benchmark (Maven project)
├── java-rdf4j/            ← RDF4J benchmark (Maven project)
├── rust-kolibrie/         ← Kolibrie benchmark (Cargo project)
├── qlever/                ← QLever benchmark (Docker)
├── virtuoso/              ← Virtuoso benchmark (Docker)
├── graphdb/               ← GraphDB benchmark (Docker)
├── dotnetrdf/             ← dotNetRDF benchmark (Docker)
└── neo4j/                 ← Neo4j + n10s benchmark (Docker)
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

## Step 2: Run benchmarks

Each benchmark script runs from its own directory and writes results to `../results/`.

### Python frameworks

```bash
cd python-maplib && python bench_maplib.py && cd ..
cd python-maplib-disk && python bench_maplib_disk.py && cd ..
cd python-oxigraph && python bench_oxigraph.py && cd ..
cd python-rdflib && python bench_rdflib.py && cd ..    # slow — expect ~5 min on medium
```

### Java frameworks

Build and run from each directory:

```bash
cd java-jena
mvn package -q
java -jar target/jena-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results
cd ..

cd java-rdf4j
mvn package -q
java -jar target/rdf4j-benchmark-1.0-SNAPSHOT.jar ../data ../queries ../results
cd ..
```

### Rust framework

```bash
cd rust-kolibrie
cargo run --release
cd ..
```

### Docker-based frameworks

Each script handles pulling images, starting containers, and cleanup:

```bash
cd qlever && python bench_qlever.py && cd ..
cd virtuoso && python bench_virtuoso.py && cd ..
cd graphdb && python bench_graphdb.py && cd ..
cd dotnetrdf && python bench_dotnetrdf.py && cd ..
cd neo4j && python bench_neo4j.py && cd ..
```

**Notes on Docker benchmarks:**
- GraphDB requires the image to be pulled manually first: `docker pull ontotext/graphdb:10.8.0`
- Neo4j automatically downloads the neosemantics (n10s) plugin JAR on first run
- dotNetRDF builds a Docker image from source (Dockerfile + C# project)
- dotNetRDF's xlarge (10M) fails with OOM — results are recorded as TIMEOUT
- All Docker containers are cleaned up automatically after benchmarking

## Step 3: View results

Open `benchmark.html` in any browser. The report includes:

- **I/O performance charts** — grouped bar charts for read/write at each scale
- **Query performance charts** — SPARQL timing comparisons
- **Scale tabs** — switch between 100K, 1M, and 10M triple datasets
- **Log scale toggle** — useful when comparing frameworks with very different speeds
- **Framework filters** — click chips to show/hide individual frameworks
- **Preset groups** — All, In-memory, Disk/server, Python, Docker-based
- **Expandable query rows** — click any query name to see the full SPARQL

## SPARQL queries

| ID | Description | Complexity |
|----|-------------|------------|
| Q1 | `COUNT` all triples | Full scan |
| Q2 | Top 20 customers by spend (`GROUP BY` + `SUM` + `ORDER BY`) | Aggregation over joins |
| Q3 | 3-entity join (customer + order + product) with country filter | Multi-pattern + filter |
| Q4 | Revenue by country/segment with `OPTIONAL` orders | OPTIONAL + aggregation |

Neo4j uses equivalent Cypher translations of these queries rather than SPARQL.

## Methodology

All frameworks use the same data files and the same queries. Each operation has a 5-minute timeout.

**Timing:** Python uses `time.perf_counter()` with garbage collection between runs. Java uses `System.nanoTime()` with JVM warmup. Rust uses `std::time::Instant`. Docker-based frameworks time the full operation including any HTTP round-trip.

**Queries:** Best of 3 runs after a warmup run.

**I/O:** Single timed run (no averaging), since allocation overhead is part of the real-world cost.

**Write operations:** Native library frameworks (maplib, oxigraph, rdflib, Jena, RDF4J, Kolibrie, dotNetRDF) benchmark writing Turtle and N-Triples. Server-based frameworks (QLever, Virtuoso, GraphDB, Neo4j) record write operations as N/A since they are database servers that don't serialize RDF files.

**oxigraph:** Uses `pyoxigraph.Store()` without a path argument, creating an anonymous temporary store backed by RocksDB.

**Neo4j + n10s:** Imports RDF via the neosemantics plugin which maps RDF triples to Neo4j's native labeled property graph model. Import times include this RDF-to-property-graph conversion. Queries are Cypher translations of the SPARQL benchmarks.

## Notes

- The xlarge dataset (~10M triples) requires significant memory. Expect 4+ GB for in-memory frameworks.
- rdflib is pure Python and will be substantially slower than the Rust-backed and Java frameworks — this is expected.
- maplib reads use `parallel=True` for multi-threaded parsing.
- maplib (disk) uses the proprietary `storage_folder` parameter. The in-memory maplib is fully open source under Apache 2.0.
- dotNetRDF cannot handle xlarge (10M triples) within its 16 GB Docker memory limit.
- Server-based Docker frameworks (QLever, Virtuoso, GraphDB, Neo4j) have query times that include ~0.5–1 ms of HTTP overhead. dotNetRDF runs in-process with no network overhead.
