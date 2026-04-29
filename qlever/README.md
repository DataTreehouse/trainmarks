# QLever Benchmark

Benchmarks [QLever](https://github.com/ad-freiburg/qlever), a high-performance
SPARQL engine developed at the University of Freiburg, using Docker.

## Prerequisites

1. **Docker** installed and running
2. Pull the QLever image:
   ```bash
   docker pull docker.qlever.io/qlever
   ```

## How it works

QLever is architecturally different from the other benchmarked frameworks:

| Operation | Other frameworks | QLever |
|-----------|-----------------|--------|
| Read Turtle | Parse into in-memory graph | Build on-disk index from Turtle |
| Read N-Triples | Parse into in-memory graph | Build on-disk index from N-Triples |
| Write Turtle | Serialise graph to file | N/A (query engine only) |
| Write N-Triples | Serialise graph to file | N/A (query engine only) |
| SPARQL queries | In-process API call | HTTP request to SPARQL endpoint |

Index building is the I/O equivalent: it's the time QLever needs before it can
answer queries. The SPARQL queries are sent via HTTP to the running server,
which adds a small network overhead compared to in-process calls — but QLever's
query execution speed is expected to more than compensate, especially on larger
datasets.

## Running

```bash
cd qlever
python bench_qlever.py
```

Results are saved to `../results/results_qlever.json`.

## Configuration

Key parameters in `bench_qlever.py`:

- `QLEVER_PORT`: HTTP port for the SPARQL endpoint (default: 7019)
- `QLEVER_IMAGE`: Docker image name (default: `docker.qlever.io/qlever`)
- `TIMEOUT`: Per-operation timeout in seconds (default: 300)
- `INDEX_TIMEOUT`: Index build timeout for xlarge (default: 600)
