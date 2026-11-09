# RDF Framework Benchmark

A reproducible benchmark comparing RDF frameworks and triplestores on I/O performance (read/write Turtle and N-Triples), SPARQL query performance, and **peak memory usage** across three dataset scales (100K, 1M, and 10M triples).

**Results:** Open `index.html` in a browser to view the interactive report with charts, framework filters, preset groups, and expandable query details.

## Frameworks tested

| Framework | Language | Store type | Version | License |
|-----------|----------|------------|---------|---------|
| maplib | Python (Rust core) | In-memory (Polars + Arrow) | 0.20.32 | Apache 2.0 |
| maplib (disk) | Python (Rust core) | Disk-backed (Polars + Arrow) | 0.20.32 | Proprietary |
| oxigraph | Python (Rust core) | In-memory (RocksDB engine, no path) | 0.5.13 | MIT / Apache 2.0 |
| oxigraph (disk) | Python (Rust core) | Disk-backed (RocksDB, on-disk path) | 0.5.13 | MIT / Apache 2.0 |
| rudof | Python (Rust core) | In-memory RDF + SHACL/ShEx toolkit | 0.3.38 | MIT / Apache 2.0 |
| rdflib | Python (pure) | In-memory (dict-of-dicts) | 7.6.0 | BSD 3-Clause |
| Apache Jena | Java | In-memory Model | 6.2.0 | Apache 2.0 |
| Eclipse RDF4J | Java | MemoryStore SAIL | 6.1.0 | EDL 1.0 |
| QLever | C++ (Docker) | On-disk index + SPARQL endpoint | pulled 2026-11-09 | Apache 2.0 |
| Virtuoso | C (Docker) | Hybrid relational/RDF, column store | 7.2.17 (r25.1) | GPL v2 |
| GraphDB | Java (Docker) | RDF4J-based, on-disk persistence | 10.8.14 | Proprietary (free tier) |
| dotNetRDF | C# (Docker) | In-memory TripleStore | 3.5.2 (.NET 10) | MIT |
| Neo4j + n10s | Java (Docker) | Native property graph + RDF import | 2025.06.2 + n10s 2025.06.1 | GPL v3 (Community) |
| TentrisDB | C++ (Docker) | Tensor-based, disk-based, worst-case-optimal joins | 1.5.0 | Proprietary (free tier) |

Versions as used in the 2026-11-09 run (Apple M3 Max, 36 GB RAM, macOS; Python 3.14, Java 26.0.1, Docker Desktop). Every run writes the exact versions it used to `results/versions.txt`.

## Prerequisites

**Python frameworks (maplib, maplib-disk, oxigraph, rudof, rdflib):**
- Python 3.10+
- `pip install maplib==0.20.32 pyoxigraph==0.5.13 pyrudof==0.3.38 rdflib==7.6.0`
- macOS: the pyrudof wheels (0.3.30 and later) link against Homebrew's OpenSSL 4, so run `brew install openssl@4` first

**Java frameworks (Jena, RDF4J):**
- Java 25+ (RDF4J 6.x ships Java 25 bytecode)
- Maven 3.8+

**Docker-based frameworks (QLever, Virtuoso, GraphDB, dotNetRDF, Neo4j, TentrisDB):**
- Docker Desktop installed and running
- Images are pulled automatically by each benchmark script, or manually:
  ```bash
  docker pull adfreiburg/qlever:commit-0998359ab0
  docker pull openlink/virtuoso-opensource-7:7.2.17-r25.1-g2850f18-ubuntu
  docker pull ontotext/graphdb:10.8.14
  docker pull mcr.microsoft.com/dotnet/sdk:10.0
  docker pull neo4j:2025.06.2-community
  docker pull ghcr.io/tentris/tentris:v1.5.0
  ```

## Directory structure

```
rdf-benchmark/
├── README.md              ← you are here
├── index.html             ← interactive results report
├── run_all.sh             ← runs every benchmark in sequence
├── update_report.py       ← writes results/*.json into index.html
├── generate_data.py       ← synthetic data generator
├── data/                  ← generated .ttl and .nt files
├── queries/               ← shared SPARQL query files (q1–q6)
├── results/               ← JSON output from each framework
├── python-maplib/         ← maplib benchmark
├── python-maplib-disk/    ← maplib disk-backed benchmark
├── python-oxigraph/       ← oxigraph benchmark
├── python-oxigraph-disk/  ← oxigraph disk-backed benchmark
├── python-rudof/          ← rudof benchmark
├── python-rdflib/         ← rdflib benchmark
├── java-jena/             ← Jena benchmark (Maven project)
├── java-rdf4j/            ← RDF4J benchmark (Maven project)
├── qlever/                ← QLever benchmark (Docker)
├── virtuoso/              ← Virtuoso benchmark (Docker)
├── graphdb/               ← GraphDB benchmark (Docker)
├── dotnetrdf/             ← dotNetRDF benchmark (Docker)
├── neo4j/                 ← Neo4j + n10s benchmark (Docker)
├── tentris/               ← TentrisDB benchmark (Docker)
└── verify/                ← result-equivalence check across engines
```

## Step 1: Generate test data

From the `rdf-benchmark/` root directory:

```bash
python generate_data.py
```

This creates Turtle (`.ttl`) and N-Triples (`.nt`) files in `data/` at three scales, plus six SPARQL query files in `queries/`:

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
cd python-rudof && python bench_rudof.py && cd ..
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

### Docker-based frameworks

Each script handles pulling images, starting containers, and cleanup:

```bash
cd qlever && python bench_qlever.py && cd ..
cd virtuoso && python bench_virtuoso.py && cd ..
cd graphdb && python bench_graphdb.py && cd ..
cd dotnetrdf && python bench_dotnetrdf.py && cd ..
cd neo4j && python bench_neo4j.py && cd ..
cd tentris && python bench_tentris.py && cd ..
```

**Notes on Docker benchmarks:**
- GraphDB requires the image to be pulled manually first: `docker pull ontotext/graphdb:10.8.14`
- GraphDB is pinned to the 10.8 line (10.8.14, the newest license-free release). From 11.0 onward, GraphDB Free is no longer bundled and requires a manually installed license, so it is not used here to keep the benchmark reproducible without registration.
- Neo4j automatically downloads the neosemantics (n10s) plugin JAR on first run
- TentrisDB is pinned to v1.5.0, which ships a native linux/arm64 image, so on Apple silicon it runs natively (earlier runs used an x86-only image under emulation, so Tentris numbers from before November 2026 are not comparable). It runs in the free (non-commercial) mode with no license. Data is loaded via the SPARQL Graph Store Protocol (HTTP POST of the N-Triples file), and `read_ntriples` times that upload into a freshly-started, empty server.
- dotNetRDF builds a Docker image from source (Dockerfile + C# project)
- dotNetRDF's xlarge (10M) fails with OOM — results are recorded as TIMEOUT
- All Docker containers are cleaned up automatically after benchmarking

## Step 3: View results

Open `index.html` in any browser. The report includes:

- **I/O performance charts** — grouped bar charts for read/write at each scale
- **Query performance charts** — SPARQL timing comparisons
- **Scale tabs** — switch between 100K, 1M, and 10M triple datasets
- **Log scale toggle** — useful when comparing frameworks with very different speeds
- **Framework filters** — click chips to show/hide individual frameworks
- **Preset groups** — All, In-memory, Disk/server, Python, Docker-based
- **Cold timing toggle** — switch between warm (best of 3) and cold (first run, no warmup) query times
- **Expandable query rows** — click any query name to see the full SPARQL

## SPARQL queries

| ID | Description | Type | Complexity |
|----|-------------|------|------------|
| Q1 | `COUNT` all triples | SELECT | Full scan |
| Q2 | Top 20 customers by spend (`GROUP BY` + `SUM` + `ORDER BY`) | SELECT | Aggregation over joins |
| Q3 | 3-entity join (customer + order + product) with country filter | SELECT | Multi-pattern + filter |
| Q4 | Revenue by country/segment with `OPTIONAL` orders | SELECT | OPTIONAL + aggregation |
| Q5 | Norwegian customer orders with product details | CONSTRUCT | Graph extraction via join |
| Q6 | Adjust product prices by category (5 conditional branches) | UPDATE | DELETE-INSERT with BIND + nested IF |

Neo4j uses equivalent Cypher translations of Q1–Q4 rather than SPARQL. Q5 (CONSTRUCT) has no Cypher equivalent. Q6 (SPARQL Update) is not supported by QLever (read-only), rudof (SELECT/CONSTRUCT only), or Neo4j (Cypher) — these are recorded as N/A.

## Methodology

All frameworks use the same data files and the same queries. The Python and Docker benchmarks give each individual operation (a load, a write, or a single query run) a 10-minute timeout; Tentris gets 30 minutes for its load. The timeout is per operation, not per engine, so a slow engine such as rdflib can take well over 10 minutes in total. The Java (Jena, RDF4J) and dotNetRDF benchmarks have no timeout.

**Timing:** Python uses `time.perf_counter()` with garbage collection between runs. Java uses `System.nanoTime()` with JVM warmup. Docker-based frameworks time the full operation including any HTTP round-trip.

**Queries:** Best of 3 runs after a warmup run. The warmup run is also recorded as the "cold" time (first execution with no cache or JIT warmup), togglable in the report.

**I/O:** Single timed run (no averaging), since allocation overhead is part of the real-world cost.

**Memory:** Every operation records a peak-memory figure, but the basis differs by engine family and the three are **not directly comparable**: Python engines sample peak process RSS (psutil), Java engines sample peak JVM heap used, and Docker engines sample peak container memory (`docker stats`). The dashboard reports per-scale peak memory per engine; compare within a basis.

**Write operations:** Native library frameworks (maplib, oxigraph, rdflib, Jena, RDF4J, dotNetRDF) benchmark writing Turtle and N-Triples. Server-based frameworks (QLever, Virtuoso, GraphDB, Neo4j) record write operations as N/A since they are database servers that don't serialize RDF files.

**oxigraph:** The `oxigraph` benchmark uses `pyoxigraph.Store()` with **no path**, which per pyoxigraph's docs keeps all data **in memory and never writes to disk** — so it measures the in-memory engine (RocksDB is the underlying engine, but no on-disk database is created). The separate `oxigraph (disk)` benchmark passes a filesystem path to `Store()`, creating a genuine on-disk RocksDB database, to measure disk-backed performance.

**Neo4j + n10s:** Imports RDF via the neosemantics plugin which maps RDF triples to Neo4j's native labeled property graph model. Import times include this RDF-to-property-graph conversion. Queries are Cypher translations of the SPARQL benchmarks.

## Notes

- The xlarge dataset (~10M triples) requires significant memory. Expect 4+ GB for in-memory frameworks.
- rdflib is pure Python and will be substantially slower than the Rust-backed and Java frameworks — this is expected.
- maplib reads use `parallel=True` for multi-threaded parsing.
- maplib (disk) uses the proprietary `storage_folder` parameter. The in-memory maplib is fully open source under Apache 2.0.
- dotNetRDF cannot handle xlarge (10M triples) within its 16 GB Docker memory limit.
- Server-based Docker frameworks (QLever, Virtuoso, GraphDB, Neo4j, TentrisDB) have query times that include ~0.5–1 ms of HTTP overhead. dotNetRDF runs in-process with no network overhead.
