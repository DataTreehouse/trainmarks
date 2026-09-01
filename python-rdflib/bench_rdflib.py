"""
Benchmark: rdflib — I/O and SPARQL queries.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation. Records peak process RSS (MB) per operation.
"""

import sys
import json
import os
import gc
from rdflib import Graph

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bench_mem import timed  # noqa: E402

FRAMEWORK = "rdflib"
QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
RESULTS = []
TIMEOUT = 600


def rec(scale, operation, seconds, peak_mb=None):
    RESULTS.append({"framework": FRAMEWORK, "scale": scale, "operation": operation,
                    "seconds": seconds, "peak_mb": peak_mb})


def load_query(name):
    with open(f"{QUERIES_DIR}/{name}.rq") as f:
        return f.read()


def bench_io(scale, ttl_path, nt_path):
    print(f"\n{'='*60}")
    print(f"rdflib — {scale} dataset")
    print(f"{'='*60}")

    def read_ttl():
        g = Graph()
        g.parse(ttl_path, format="turtle")
        return g
    g, t, m = timed("Read Turtle", read_ttl, timeout=TIMEOUT)
    if t is not None:
        rec(scale, "read_turtle", t, m)
        print(f"  Triple count: {len(g)}")
    else:
        rec(scale, "read_turtle", "TIMEOUT")
        return None

    out_ttl = f"../data/{scale}_rdflib_out.ttl"
    _, t, m = timed("Write Turtle", lambda: g.serialize(destination=out_ttl, format="turtle"), timeout=TIMEOUT)
    if t is not None:
        rec(scale, "write_turtle", t, m)
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        rec(scale, "write_turtle", "TIMEOUT")

    out_nt = f"../data/{scale}_rdflib_out.nt"
    _, t, m = timed("Write N-Triples", lambda: g.serialize(destination=out_nt, format="nt"), timeout=TIMEOUT)
    if t is not None:
        rec(scale, "write_ntriples", t, m)
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        rec(scale, "write_ntriples", "TIMEOUT")

    def read_nt():
        g2 = Graph()
        g2.parse(nt_path, format="nt")
        return g2
    _, t, m = timed("Read N-Triples", read_nt, timeout=TIMEOUT)
    if t is not None:
        rec(scale, "read_ntriples", t, m)
    else:
        rec(scale, "read_ntriples", "TIMEOUT")

    return g


def bench_queries(g, scale):
    if g is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        q = load_query(qname)
        is_update = any(line.strip().upper().startswith("DELETE") or line.strip().upper().startswith("INSERT")
                        for line in q.split("\n") if not line.strip().upper().startswith("PREFIX"))

        def run_q(query=q, update=is_update):
            if update:
                return g.update(query)
            return list(g.query(query))

        _, t_warmup, m_cold = timed(f"  {qname} (warmup)", run_q, warmup=True, timeout=TIMEOUT)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            rec(scale, f"query_{qname}", "TIMEOUT")
            rec(scale, f"query_{qname}_cold", "TIMEOUT")
            continue
        rec(scale, f"query_{qname}_cold", t_warmup, m_cold)

        times, peaks = [], []
        for _ in range(3):
            _, t, m = timed(f"  {qname}", run_q, warmup=True, timeout=TIMEOUT)
            if t is not None:
                times.append(t)
                peaks.append(m)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            rec(scale, f"query_{qname}", best, max([p for p in peaks if p is not None], default=None))
        else:
            print(f"    {qname}: TIMEOUT")
            rec(scale, f"query_{qname}", "TIMEOUT")


if __name__ == "__main__":
    for scale in ["medium", "large", "xlarge"]:
        g = bench_io(scale, f"../data/{scale}.ttl", f"../data/{scale}.nt")
        bench_queries(g, scale)
        del g
        gc.collect()

    with open("../results/results_rdflib.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_rdflib.json")
