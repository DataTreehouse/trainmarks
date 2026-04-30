"""
Benchmark: rdflib — I/O and SPARQL queries.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation.
"""

import time
import json
import os
import gc
import signal
from rdflib import Graph

QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
RESULTS = []
TIMEOUT = 600  # 10 minutes


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")


def timed(label, fn, warmup=False, timeout=TIMEOUT):
    """Run fn with timeout, return (result, elapsed_seconds)."""
    gc.collect()
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    try:
        t0 = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - t0
        signal.alarm(0)
        if not warmup:
            print(f"  {label}: {elapsed:.4f}s")
        return result, elapsed
    except TimeoutError:
        signal.alarm(0)
        print(f"  {label}: TIMEOUT (>{timeout}s)")
        return None, None


def load_query(name):
    with open(f"{QUERIES_DIR}/{name}.rq") as f:
        return f.read()


def bench_io(scale, ttl_path, nt_path):
    """Benchmark read and write for a given scale."""
    print(f"\n{'='*60}")
    print(f"rdflib — {scale} dataset")
    print(f"{'='*60}")

    # --- Read Turtle ---
    def read_ttl():
        g = Graph()
        g.parse(ttl_path, format="turtle")
        return g
    g, t_read_ttl = timed("Read Turtle", read_ttl)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
        print(f"  Triple count: {len(g)}")
    else:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})
        return None

    # --- Write Turtle ---
    out_ttl = f"../data/{scale}_rdflib_out.ttl"
    _, t_write_ttl = timed("Write Turtle", lambda: g.serialize(destination=out_ttl, format="turtle"))
    if t_write_ttl is not None:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "write_turtle", "seconds": t_write_ttl})
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "write_turtle", "seconds": "TIMEOUT"})

    # --- Write N-Triples ---
    out_nt = f"../data/{scale}_rdflib_out.nt"
    _, t_write_nt = timed("Write N-Triples", lambda: g.serialize(destination=out_nt, format="nt"))
    if t_write_nt is not None:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "write_ntriples", "seconds": t_write_nt})
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "write_ntriples", "seconds": "TIMEOUT"})

    # --- Read N-Triples ---
    def read_nt():
        g2 = Graph()
        g2.parse(nt_path, format="nt")
        return g2
    _, t_read_nt = timed("Read N-Triples", read_nt)
    if t_read_nt is not None:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "rdflib", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

    return g


def bench_queries(g, scale):
    """Benchmark SPARQL queries."""
    if g is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
        q = load_query(qname)
        # Warmup run
        _, t_warmup = timed(f"  {qname} (warmup)", lambda: list(g.query(q)), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "rdflib", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            continue
        # Timed run (best of 3)
        times = []
        for _ in range(3):
            _, t = timed(f"  {qname}", lambda: list(g.query(q)), warmup=True)
            if t is not None:
                times.append(t)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            RESULTS.append({"framework": "rdflib", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "rdflib", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


if __name__ == "__main__":
    # Medium
    g_med = bench_io("medium", "../data/medium.ttl", "../data/medium.nt")
    bench_queries(g_med, "medium")
    del g_med
    gc.collect()

    # Large
    g_large = bench_io("large", "../data/large.ttl", "../data/large.nt")
    bench_queries(g_large, "large")
    del g_large
    gc.collect()

    # XLarge
    g_xlarge = bench_io("xlarge", "../data/xlarge.ttl", "../data/xlarge.nt")
    bench_queries(g_xlarge, "xlarge")
    del g_xlarge
    gc.collect()

    # Save results
    with open("../results/results_rdflib.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_rdflib.json")
