"""
Benchmark: maplib — I/O and SPARQL queries. IN-MEMORY store.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation. Records peak process RSS (MB) per operation.
"""

import sys
import json
import os
import gc
from maplib import Model

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bench_mem import timed  # noqa: E402

FRAMEWORK = "maplib"
QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
RESULTS = []
TIMEOUT = 600


def rec(scale, operation, seconds, peak_mb=None):
    RESULTS.append({"framework": FRAMEWORK, "scale": scale, "operation": operation,
                    "seconds": seconds, "peak_mb": peak_mb})


def load_query(name):
    with open(f"{QUERIES_DIR}/{name}.rq") as f:
        return f.read()


def new_model():
    return Model()


def bench_io(scale, ttl_path, nt_path):
    print(f"\n{'='*60}")
    print(f"maplib — {scale} dataset")
    print(f"{'='*60}")

    def read_ttl():
        m = new_model()
        m.read(ttl_path, parallel=True)
        return m
    m, t, mem = timed("Read Turtle (parallel=True)", read_ttl, timeout=TIMEOUT)
    if t is not None:
        rec(scale, "read_turtle", t, mem)
    else:
        rec(scale, "read_turtle", "TIMEOUT")
        return None

    count = m.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }", streaming=True)["c"][0]
    print(f"  Triple count: {count}")

    out_ttl = f"../data/{scale}_maplib_out.ttl"
    _, t, mem = timed("Write Turtle", lambda: m.write(out_ttl, format="turtle"), timeout=TIMEOUT)
    if t is not None:
        rec(scale, "write_turtle", t, mem)
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        rec(scale, "write_turtle", "TIMEOUT")

    out_nt = f"../data/{scale}_maplib_out.nt"
    _, t, mem = timed("Write N-Triples", lambda: m.write(out_nt, format="ntriples"), timeout=TIMEOUT)
    if t is not None:
        rec(scale, "write_ntriples", t, mem)
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        rec(scale, "write_ntriples", "TIMEOUT")

    def read_nt():
        m2 = new_model()
        m2.read(nt_path, parallel=True)
        return m2
    _, t, mem = timed("Read N-Triples (parallel=True)", read_nt, timeout=TIMEOUT)
    if t is not None:
        rec(scale, "read_ntriples", t, mem)
    else:
        rec(scale, "read_ntriples", "TIMEOUT")

    return m


def bench_queries(m, scale):
    if m is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        q = load_query(qname)
        is_construct = any(line.strip().upper().startswith("CONSTRUCT") for line in q.split("\n"))
        is_update = any(line.strip().upper().startswith("DELETE") or line.strip().upper().startswith("INSERT")
                        for line in q.split("\n") if not line.strip().upper().startswith("PREFIX"))

        def run_query(query=q, construct=is_construct, update=is_update):
            if update:
                return m.update(query)
            elif construct:
                return m.query(query)
            else:
                return m.query(query, streaming=True)

        _, t_warmup, m_cold = timed(f"  {qname} (warmup)", run_query, warmup=True, timeout=TIMEOUT)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            rec(scale, f"query_{qname}", "TIMEOUT")
            rec(scale, f"query_{qname}_cold", "TIMEOUT")
            continue
        rec(scale, f"query_{qname}_cold", t_warmup, m_cold)

        times, peaks = [], []
        for _ in range(3):
            _, t, mem = timed(f"  {qname}", run_query, warmup=True, timeout=TIMEOUT)
            if t is not None:
                times.append(t)
                peaks.append(mem)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            rec(scale, f"query_{qname}", best, max([p for p in peaks if p is not None], default=None))
        else:
            print(f"    {qname}: TIMEOUT")
            rec(scale, f"query_{qname}", "TIMEOUT")


if __name__ == "__main__":
    for scale in ["medium", "large", "xlarge"]:
        m_ = bench_io(scale, f"../data/{scale}.ttl", f"../data/{scale}.nt")
        bench_queries(m_, scale)
        del m_
        gc.collect()

    with open("../results/results_maplib.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_maplib.json")
