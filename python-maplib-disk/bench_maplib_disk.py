"""
Benchmark: maplib (disk-backed) — I/O and SPARQL queries.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation.

Same as the in-memory maplib benchmark, but uses storage_folder to
write the backing store to disk instead of keeping everything in RAM.
"""

import time
import json
import os
import gc
import signal
import shutil
from maplib import Model

QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STORAGE_DIR = os.path.join(os.path.dirname(__file__), "maplib-storage")
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


def clean_storage():
    """Remove and recreate the storage directory."""
    if os.path.exists(STORAGE_DIR):
        shutil.rmtree(STORAGE_DIR)
    os.makedirs(STORAGE_DIR, exist_ok=True)


def bench_io(scale, ttl_path, nt_path):
    """Benchmark read and write for a given scale (disk-backed)."""
    print(f"\n{'='*60}")
    print(f"maplib (disk) — {scale} dataset")
    print(f"{'='*60}")

    storage_path = os.path.join(STORAGE_DIR, f"{scale}")

    # --- Read Turtle (parallel, disk-backed) ---
    def read_ttl():
        if os.path.exists(storage_path):
            shutil.rmtree(storage_path)
        m = Model(storage_folder=storage_path)
        m.read(ttl_path, parallel=True)
        return m
    m, t_read_ttl = timed("Read Turtle (parallel=True, disk)", read_ttl)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
    else:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})
        return None

    # Count triples
    count = m.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }", streaming=True)["c"][0]
    print(f"  Triple count: {count}")

    # --- Write Turtle ---
    out_ttl = os.path.join(DATA_DIR, f"{scale}_maplib_disk_out.ttl")
    _, t_write_ttl = timed("Write Turtle", lambda: m.write(out_ttl, format="turtle"))
    if t_write_ttl is not None:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "write_turtle", "seconds": t_write_ttl})
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "write_turtle", "seconds": "TIMEOUT"})

    # --- Write N-Triples ---
    out_nt = os.path.join(DATA_DIR, f"{scale}_maplib_disk_out.nt")
    _, t_write_nt = timed("Write N-Triples", lambda: m.write(out_nt, format="ntriples"))
    if t_write_nt is not None:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "write_ntriples", "seconds": t_write_nt})
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "write_ntriples", "seconds": "TIMEOUT"})

    # --- Read N-Triples (parallel, disk-backed) ---
    def read_nt():
        nt_storage = storage_path + "_nt"
        if os.path.exists(nt_storage):
            shutil.rmtree(nt_storage)
        m2 = Model(storage_folder=nt_storage)
        m2.read(nt_path, parallel=True)
        return m2
    _, t_read_nt = timed("Read N-Triples (parallel=True, disk)", read_nt)
    if t_read_nt is not None:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

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
            RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
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
            RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "maplib_disk", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


def save_results():
    """Save results incrementally so partial runs aren't lost."""
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "results_maplib_disk.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"  Results saved ({len(RESULTS)} entries)")


if __name__ == "__main__":
    clean_storage()

    for scale in ["medium", "large", "xlarge"]:
        ttl_path = os.path.join(DATA_DIR, f"{scale}.ttl")
        nt_path = os.path.join(DATA_DIR, f"{scale}.nt")

        if not os.path.exists(ttl_path):
            print(f"\n  Skipping {scale} — {ttl_path} not found")
            continue

        try:
            m = bench_io(scale, ttl_path, nt_path)
            bench_queries(m, scale)
        except Exception as e:
            print(f"\n  ERROR on {scale}: {e}")
            print("  Saving partial results and continuing...")
        finally:
            save_results()
            # Free memory before next scale
            try:
                del m
            except NameError:
                pass
            gc.collect()

    print(f"\nAll done — results saved to results/results_maplib_disk.json")

    # Clean up storage
    clean_storage()
