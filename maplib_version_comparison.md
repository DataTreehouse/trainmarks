# maplib benchmark: 0.20.15 vs 0.20.19

> Old numbers = original run on your Mac (maplib 0.20.15). New numbers = re-run in Claude's Linux sandbox (maplib 0.20.19).
> **Different hardware** — treat absolute deltas as indicative only. For a valid version comparison, re-run both on the same machine.

## medium (~100K triples)

| Operation | 0.20.15 (s) | 0.20.19 (s) | Δ |
|---|---|---|---|
| Read Turtle | 0.1394 | 0.1365 | -2% |
| Write Turtle | 0.1118 | 0.0755 | -32% |
| Write N-Triples | 0.0126 | 0.0165 | +31% |
| Read N-Triples | 0.0765 | 0.1343 | +76% |
| Q1 count | 0.0022 | 0.0019 | -13% |
| Q2 top customers | 0.0018 | 0.0017 | -4% |
| Q3 3-way join | 0.0032 | 0.0024 | -25% |
| Q4 optional agg | 0.0037 | 0.0026 | -30% |
| Q5 construct | 0.0095 | 0.0070 | -26% |
| Q6 update | 0.0033 | 0.0031 | -7% |

## large (~1M triples)

| Operation | 0.20.15 (s) | 0.20.19 (s) | Δ |
|---|---|---|---|
| Read Turtle | 0.8020 | 1.3826 | +72% |
| Write Turtle | 0.7640 | 0.5164 | -32% |
| Write N-Triples | 0.0751 | 0.1062 | +41% |
| Read N-Triples | 0.7857 | 1.5053 | +92% |
| Q1 count | 0.0109 | 0.0111 | +2% |
| Q2 top customers | 0.0039 | 0.0043 | +9% |
| Q3 3-way join | 0.0065 | 0.0063 | -4% |
| Q4 optional agg | 0.0080 | 0.0076 | -5% |
| Q5 construct | 0.0172 | 0.0133 | -22% |
| Q6 update | 0.0052 | 0.0034 | -34% |

## xlarge (~10M triples)

| Operation | 0.20.15 (s) | 0.20.19 (s) | Δ |
|---|---|---|---|
| Read Turtle | 9.2657 | 17.1292 | +85% |
| Write Turtle | 7.5203 | 5.8387 | -22% |
| Write N-Triples | 0.6778 | 1.2608 | +86% |
| Read N-Triples | 9.5568 | 16.9483 | +77% |
| Q1 count | 0.0772 | 0.1737 | +125% |
| Q2 top customers | 0.0185 | 0.0477 | +158% |
| Q3 3-way join | 0.0436 | 0.1026 | +136% |
| Q4 optional agg | 0.0473 | 0.1219 | +158% |
| Q5 construct | 0.0784 | 0.1208 | +54% |
| Q6 update | 0.0192 | 0.0187 | -3% |
