# Virtuoso Benchmark

Benchmarks Virtuoso Open-Source (via Docker) for I/O and SPARQL query performance.

## Prerequisites

- Docker installed and running
- Benchmark data files generated (run `python generate_data.py` from the parent directory)

## Setup

```bash
# Pull the Virtuoso image
docker pull openlink/virtuoso-opensource-7:latest
```

## Running

```bash
cd rdf-benchmark/virtuoso
python bench_virtuoso.py
```

Results are saved to `../results/results_virtuoso.json`.

## How it works

- **I/O**: "Read" operations measure bulk-loading via `ld_dir()` + `rdf_loader_run()` in isql.
  Write operations are N/A since Virtuoso is a database server, not a serialisation tool.
- **SPARQL**: Queries are sent to the HTTP endpoint (`/sparql`). Best of 3 after warmup.
- A fresh container is started for each dataset scale with tuned buffer settings.
- Port 8891 (HTTP) and 1112 (ISQL) are used to avoid conflicts with other services.
