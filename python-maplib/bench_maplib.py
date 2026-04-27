"""
Benchmark: maplib — I/O and SPARQL queries.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation.
"""

import time
import json
import os
import gc
import signal
from maplib import Model

QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
RESULTS = []
TIMEOUT = 300  # 5 minutes


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
    print(f"maplib — {scale} dataset")
    print(f"{'='*60}")

    # --- Read Turtle (parallel) ---
    def read_ttl():
        m = Model()
        m.read(ttl_path, parallel=True)
        return m
    m, t_read_ttl = timed("Read Turtle (parallel=True)", read_ttl)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
    else:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})
        return None

    # Count triples
    count = m.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }", streaming=True)["c"][0]
    print(f"  Triple count: {count}")

    # --- Write Turtle ---
    out_ttl = f"../data/{scale}_maplib_out.ttl"
    _, t_write_ttl = timed("Write Turtle", lambda: m.write(out_ttl))
    if t_write_ttl is not None:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "write_turtle", "seconds": t_write_ttl})
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "write_turtle", "seconds": "TIMEOUT"})

    # --- Write N-Triples ---
    out_nt = f"../data/{scale}_maplib_out.nt"
    _, t_write_nt = timed("Write N-Triples", lambda: m.write(out_nt, format="ntriples"))
    if t_write_nt is not None:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "write_ntriples", "seconds": t_write_nt})
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "write_ntriples", "seconds": "TIMEOUT"})

    # --- Read N-Triples (parallel) ---
    def read_nt():
        m2 = Model()
        m2.read(nt_path, parallel=True)
        return m2
    _, t_read_nt = timed("Read N-Triples (parallel=True)", read_nt)
    if t_read_nt is not None:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "maplib", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

    return m


def bench_queries(m, scale):
    """Benchmark SPARQL queries."""
    if m is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
        q = load_query(qname)
        # Warmup run
        _, t_warmup = timed(f"  {qname} (warmup)", lambda: m.query(q, streaming=True), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "maplib", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            continue
        # Timed run (best of 3)
        times = []
        for _ in range(3):
            _, t = timed(f"  {qname}", lambda: m.query(q, streaming=True), warmup=True)
            if t is not None:
                times.append(t)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            RESULTS.append({"framework": "maplib", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "maplib", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


if __name__ == "__main__":
    # Medium
    m_med = bench_io("medium", "../data/medium.ttl", "../data/medium.nt")
    bench_queries(m_med, "medium")
    del m_med
    gc.collect()

    # Large
    m_large = bench_io("large", "../data/large.ttl", "../data/large.nt")
    bench_queries(m_large, "large")
    del m_large
    gc.collect()

    # XLarge
    m_xlarge = bench_io("xlarge", "../data/xlarge.ttl", "../data/xlarge.nt")
    bench_queries(m_xlarge, "xlarge")

    # Save results
    with open("../results/results_maplib.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_maplib.json")
