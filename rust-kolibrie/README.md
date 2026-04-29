# Kolibrie Benchmark

Benchmarks [Kolibrie](https://github.com/StreamIntelligenceLab/Kolibrie), a Rust-based
RDF query engine from KU Leuven's Stream Intelligence Lab.

## Prerequisites

- **Rust** 1.60+ (install via [rustup](https://rustup.rs/))
- Run `python generate_data.py` from the repo root first to create the test datasets

## Building

```bash
cd rust-kolibrie
cargo build --release
```

The first build will clone the Kolibrie repository from GitHub and compile it
as a dependency. This takes a few minutes.

## Running

```bash
cargo run --release
```

Results are saved to `../results/results_kolibrie.json`.

## What it measures

| Operation | Method |
|-----------|--------|
| Read Turtle | `SparqlDatabase::parse_turtle()` (from string) |
| Write Turtle | `SparqlDatabase::generate_turtle()` |
| Write N-Triples | `SparqlDatabase::generate_ntriples()` |
| Read N-Triples | `SparqlDatabase::parse_ntriples_and_add()` (from string) |
| SPARQL queries | `execute_query()` with warmup + best of 3 |

Note: Kolibrie's parse methods take string input, so file read time is
included in the measurement (read file into string, then parse). This is
comparable to the other frameworks which also include file I/O in their
read measurements.

## About Kolibrie

Kolibrie features dictionary-encoded triple storage, a Volcano-style query
optimizer (Streamertail), SIMD-accelerated filtering and aggregation, and
streaming RDF support via RSP-QL. It is licensed under MPL-2.0.
