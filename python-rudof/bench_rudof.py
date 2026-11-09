"""
Benchmark: rudof (via pyrudof) — I/O and SPARQL queries. IN-MEMORY.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 10 minutes per operation.

rudof is a Rust-based RDF toolkit with Python bindings. It supports
SELECT and CONSTRUCT queries via its built-in SPARQL engine.
SPARQL Update (DELETE/INSERT) is not supported — Q6 is recorded as N/A.

Each result records peak process RSS (MB) during the operation, sampled
by a background thread, so memory use can be compared against timing.
"""

import time
import json
import os
import gc
import signal
import threading

import pyrudof

FRAMEWORK = "rudof"
QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
RESULTS = []
TIMEOUT = 600  # 10 minutes

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


def load_query(name):
    with open(f"{QUERIES_DIR}/{name}.rq") as f:
        return f.read()


def new_rudof():
    """Fresh Rudof instance (in-memory)."""
    return pyrudof.Rudof()


def bench_io(scale, ttl_path, nt_path):
    print(f"\n{'='*60}")
    print(f"rudof (in-memory) — {scale} dataset")
    print(f"{'='*60}")

    # --- Read Turtle ---
    def read_ttl():
        r = new_rudof()
        r.read_data(ttl_path, format=pyrudof.RDFFormat.Turtle)
        return r
    rudof_inst, t_read_ttl, m = timed("Read Turtle", read_ttl)
    if t_read_ttl is not None:
        rec(scale, "read_turtle", t_read_ttl, m)
        # Count triples to verify
        rudof_inst.read_query("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }")
        res = rudof_inst.run_query()
        py = res.to_python()
        count = py[0]["?count"].split('"')[1] if py else "?"
        print(f"  Triple count: {count}")
    else:
        rec(scale, "read_turtle", "TIMEOUT")
        return None

    # --- Write Turtle ---
    out_ttl = os.path.join(os.path.dirname(__file__), "..", "data", f"{scale}_rudof_out.ttl")
    def write_ttl():
        data = rudof_inst.serialize_data(format=pyrudof.ResultDataFormat.Turtle)
        with open(out_ttl, "w") as f:
            f.write(data)
    _, t_write_ttl, m = timed("Write Turtle", write_ttl)
    if t_write_ttl is not None:
        rec(scale, "write_turtle", t_write_ttl, m)
        if os.path.exists(out_ttl):
            os.remove(out_ttl)
    else:
        rec(scale, "write_turtle", "TIMEOUT")

    # --- Write N-Triples ---
    out_nt = os.path.join(os.path.dirname(__file__), "..", "data", f"{scale}_rudof_out.nt")
    def write_nt():
        data = rudof_inst.serialize_data(format=pyrudof.ResultDataFormat.NTriples)
        with open(out_nt, "w") as f:
            f.write(data)
    _, t_write_nt, m = timed("Write N-Triples", write_nt)
    if t_write_nt is not None:
        rec(scale, "write_ntriples", t_write_nt, m)
        if os.path.exists(out_nt):
            os.remove(out_nt)
    else:
        rec(scale, "write_ntriples", "TIMEOUT")

    # --- Read N-Triples ---
    def read_nt():
        r = new_rudof()
        r.read_data(nt_path, format=pyrudof.RDFFormat.NTriples)
        return r
    _, t_read_nt, m = timed("Read N-Triples", read_nt)
    if t_read_nt is not None:
        rec(scale, "read_ntriples", t_read_nt, m)
    else:
        rec(scale, "read_ntriples", "TIMEOUT")

    return rudof_inst


def bench_queries(rudof_inst, scale):
    if rudof_inst is None:
        print(f"\n  Skipping queries ({scale}) — read failed")
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities",
                   "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        q = load_query(qname)

        # rudof does not support SPARQL Update (DELETE/INSERT)
        is_update = any(
            line.strip().upper().startswith("DELETE") or line.strip().upper().startswith("INSERT")
            for line in q.split("\n")
            if not line.strip().upper().startswith("PREFIX")
        )
        if is_update:
            print(f"    {qname}: N/A (SPARQL Update not supported)")
            rec(scale, f"query_{qname}", "N/A")
            rec(scale, f"query_{qname}_cold", "N/A")
            continue

        def run_q(query=q):
            rudof_inst.read_query(query)
            return rudof_inst.run_query()

        # Cold run (first execution)
        _, t_warmup, m_cold = timed(f"  {qname} (warmup)", run_q, warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            rec(scale, f"query_{qname}", "TIMEOUT")
            rec(scale, f"query_{qname}_cold", "TIMEOUT")
            continue
        rec(scale, f"query_{qname}_cold", t_warmup, m_cold)

        # Best of 3 (warm)
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
    print(f"pyrudof version: {pyrudof.Rudof().get_version()}")

    for scale in ["medium", "large", "xlarge"]:
        ttl = os.path.join(os.path.dirname(__file__), "..", "data", f"{scale}.ttl")
        nt = os.path.join(os.path.dirname(__file__), "..", "data", f"{scale}.nt")
        r = bench_io(scale, ttl, nt)
        bench_queries(r, scale)
        del r
        gc.collect()

    out_path = os.path.join(os.path.dirname(__file__), "..", "results", "results_rudof.json")
    with open(out_path, "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults saved to results_rudof.json")
