"""
Benchmark: oxigraph (via pyoxigraph) — I/O and SPARQL queries. DISK-BACKED store.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation.

Storage note: this variant passes a filesystem path to pyoxigraph's Store(),
so data is persisted to an on-disk RocksDB database (unlike the default
python-oxigraph benchmark, which uses Store() with no path = in-memory).

Each result records peak process RSS (MB) during the operation.
"""

import time
import json
import os
import gc
import signal
import shutil
import tempfile
import threading
from pyoxigraph import Store, RdfFormat, DefaultGraph

FRAMEWORK = "oxigraph_disk"
QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
STORAGE_BASE = os.path.join(os.path.dirname(__file__), "oxigraph-storage")
RESULTS = []
TIMEOUT = 600  # 10 minutes

# Track on-disk store directories so we can clean them up.
_STORE_DIRS = []

# --- peak-memory sampling -------------------------------------------------
try:
    import psutil
    _PROC = psutil.Process(os.getpid())
except Exception:
    psutil = None
    _PROC = None


class _MemSampler:
    """Background thread sampling process RSS to capture an operation's peak."""

    def __init__(self, interval=0.1):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            if _PROC is not None:
                try:
                    rss = _PROC.memory_info().rss
                    if rss > self.peak:
                        self.peak = rss
                except Exception:
                    pass
            self._stop.wait(self.interval)

    def __enter__(self):
        if _PROC is not None:
            self.peak = _PROC.memory_info().rss
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    @property
    def peak_mb(self):
        return round(self.peak / (1024 * 1024), 1) if self.peak else None


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")


def timed(label, fn, warmup=False, timeout=TIMEOUT):
    """Run fn with timeout while sampling peak RSS. Returns (result, seconds, peak_mb)."""
    gc.collect()
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    try:
        with _MemSampler() as mem:
            t0 = time.perf_counter()
            result = fn()
            elapsed = time.perf_counter() - t0
        signal.alarm(0)
        if not warmup:
            print(f"  {label}: {elapsed:.4f}s  (peak {mem.peak_mb} MB)")
        return result, elapsed, mem.peak_mb
    except TimeoutError:
        signal.alarm(0)
        print(f"  {label}: TIMEOUT (>{timeout}s)")
        return None, None, None


def rec(scale, operation, seconds, peak_mb=None):
    RESULTS.append({
        "framework": FRAMEWORK, "scale": scale, "operation": operation,
        "seconds": seconds, "peak_mb": peak_mb,
    })


def new_store():
    """Fresh on-disk RocksDB store in a unique directory (tracked for cleanup)."""
    os.makedirs(STORAGE_BASE, exist_ok=True)
    d = tempfile.mkdtemp(prefix="store_", dir=STORAGE_BASE)
    _STORE_DIRS.append(d)
    return Store(d)


def cleanup_stores():
    """Drop RocksDB locks (gc) and remove all on-disk store directories."""
    gc.collect()
    for d in _STORE_DIRS:
        shutil.rmtree(d, ignore_errors=True)
    _STORE_DIRS.clear()


def load_query(name):
    with open(f"{QUERIES_DIR}/{name}.rq") as f:
        return f.read()


def bench_io(scale, ttl_path, nt_path):
    print(f"\n{'='*60}")
    print(f"oxigraph (disk-backed RocksDB) — {scale} dataset")
    print(f"{'='*60}")

    # --- Read Turtle ---
    def read_ttl():
        store = new_store()
        with open(ttl_path, "rb") as f:
            store.load(f, format=RdfFormat.TURTLE)
        return store
    store, t_read_ttl, m = timed("Read Turtle", read_ttl)
    if t_read_ttl is not None:
        rec(scale, "read_turtle", t_read_ttl, m)
        print(f"  Triple count: {len(store)}")
    else:
        rec(scale, "read_turtle", "TIMEOUT")
        return None

    # --- Write Turtle ---
    out_ttl = f"../data/{scale}_oxigraph_disk_out.ttl"
    def write_ttl():
        with open(out_ttl, "wb") as f:
            store.dump(f, format=RdfFormat.TURTLE, from_graph=DefaultGraph())
    _, t_write_ttl, m = timed("Write Turtle", write_ttl)
    if t_write_ttl is not None:
        rec(scale, "write_turtle", t_write_ttl, m)
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        rec(scale, "write_turtle", "TIMEOUT")

    # --- Write N-Triples ---
    out_nt = f"../data/{scale}_oxigraph_disk_out.nt"
    def write_nt():
        with open(out_nt, "wb") as f:
            store.dump(f, format=RdfFormat.N_TRIPLES, from_graph=DefaultGraph())
    _, t_write_nt, m = timed("Write N-Triples", write_nt)
    if t_write_nt is not None:
        rec(scale, "write_ntriples", t_write_nt, m)
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        rec(scale, "write_ntriples", "TIMEOUT")

    # --- Read N-Triples (fresh disk store) ---
    def read_nt():
        s2 = new_store()
        with open(nt_path, "rb") as f:
            s2.load(f, format=RdfFormat.N_TRIPLES)
        return s2
    _, t_read_nt, m = timed("Read N-Triples", read_nt)
    if t_read_nt is not None:
        rec(scale, "read_ntriples", t_read_nt, m)
    else:
        rec(scale, "read_ntriples", "TIMEOUT")

    return store


def bench_queries(store, scale):
    if store is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        q = load_query(qname)
        is_update = any(line.strip().upper().startswith("DELETE") or line.strip().upper().startswith("INSERT")
                        for line in q.split("\n") if not line.strip().upper().startswith("PREFIX"))

        def run_q(query=q, update=is_update):
            if update:
                return store.update(query)
            else:
                return list(store.query(query))

        # Warmup (also recorded as cold timing)
        _, t_warmup, m_cold = timed(f"  {qname} (warmup)", run_q, warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            rec(scale, f"query_{qname}", "TIMEOUT")
            rec(scale, f"query_{qname}_cold", "TIMEOUT")
            continue
        rec(scale, f"query_{qname}_cold", t_warmup, m_cold)

        # Best of 3
        times = []
        peaks = []
        for _ in range(3):
            _, t, m = timed(f"  {qname}", run_q, warmup=True)
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
    try:
        for scale in ["medium", "large", "xlarge"]:
            s = bench_io(scale, f"../data/{scale}.ttl", f"../data/{scale}.nt")
            bench_queries(s, scale)
            del s
            cleanup_stores()  # drop RocksDB dirs before the next scale
            gc.collect()
    finally:
        cleanup_stores()

    with open("../results/results_oxigraph_disk.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_oxigraph_disk.json")
