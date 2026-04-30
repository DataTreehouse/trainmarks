"""
Benchmark: oxigraph (via pyoxigraph) — I/O and SPARQL queries.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation.
"""

import time
import json
import os
import gc
import signal
from pyoxigraph import Store, RdfFormat, DefaultGraph

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
    print(f"\n{'='*60}")
    print(f"oxigraph — {scale} dataset")
    print(f"{'='*60}")

    # --- Read Turtle ---
    def read_ttl():
        store = Store()
        with open(ttl_path, "rb") as f:
            store.load(f, format=RdfFormat.TURTLE)
        return store
    store, t_read_ttl = timed("Read Turtle", read_ttl)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
        print(f"  Triple count: {len(store)}")
    else:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})
        return None

    # --- Write Turtle ---
    out_ttl = f"../data/{scale}_oxigraph_out.ttl"
    def write_ttl():
        with open(out_ttl, "wb") as f:
            store.dump(f, format=RdfFormat.TURTLE, from_graph=DefaultGraph())
    _, t_write_ttl = timed("Write Turtle", write_ttl)
    if t_write_ttl is not None:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "write_turtle", "seconds": t_write_ttl})
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "write_turtle", "seconds": "TIMEOUT"})

    # --- Write N-Triples ---
    out_nt = f"../data/{scale}_oxigraph_out.nt"
    def write_nt():
        with open(out_nt, "wb") as f:
            store.dump(f, format=RdfFormat.N_TRIPLES, from_graph=DefaultGraph())
    _, t_write_nt = timed("Write N-Triples", write_nt)
    if t_write_nt is not None:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "write_ntriples", "seconds": t_write_nt})
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "write_ntriples", "seconds": "TIMEOUT"})

    # --- Read N-Triples ---
    def read_nt():
        s2 = Store()
        with open(nt_path, "rb") as f:
            s2.load(f, format=RdfFormat.N_TRIPLES)
        return s2
    _, t_read_nt = timed("Read N-Triples", read_nt)
    if t_read_nt is not None:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

    return store


def bench_queries(store, scale):
    if store is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
        q = load_query(qname)

        # Warmup
        _, t_warmup = timed(f"  {qname} (warmup)", lambda: list(store.query(q)), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            continue

        # Best of 3
        times = []
        for _ in range(3):
            _, t = timed(f"  {qname}", lambda: list(store.query(q)), warmup=True)
            if t is not None:
                times.append(t)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "oxigraph", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


if __name__ == "__main__":
    # Medium
    s_med = bench_io("medium", "../data/medium.ttl", "../data/medium.nt")
    bench_queries(s_med, "medium")
    del s_med
    gc.collect()

    # Large
    s_large = bench_io("large", "../data/large.ttl", "../data/large.nt")
    bench_queries(s_large, "large")
    del s_large
    gc.collect()

    # XLarge
    s_xlarge = bench_io("xlarge", "../data/xlarge.ttl", "../data/xlarge.nt")
    bench_queries(s_xlarge, "xlarge")
    del s_xlarge
    gc.collect()

    # Save results
    with open("../results/results_oxigraph.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_oxigraph.json")
