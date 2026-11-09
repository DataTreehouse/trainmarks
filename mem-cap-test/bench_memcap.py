"""
Constrained-memory test for IN-MEMORY maplib.

Runs the same read / query workload as python-maplib/bench_maplib.py, but is
meant to run INSIDE a Docker container with a hard `--memory` limit so we can
watch how in-memory maplib behaves as available RAM shrinks.

Key differences from the normal bench:
  * reads data from /data (read-only), writes temp output to /tmp, results to /out
  * saves results after EVERY operation, so if the kernel OOM-kills the process
    (SIGKILL, uncatchable), the JSON still shows exactly how far it got
  * prints progress with flush so the container log is a live trace

Usage (inside container):  python bench_memcap.py <scales> <cap_label>
  e.g.  python bench_memcap.py medium,large,xlarge 2g
"""
import sys, os, gc, json, time, signal, threading
from maplib import Model

DATA = "/data"
QUERIES = "/queries"
OUT = "/out"
SCALES = (sys.argv[1] if len(sys.argv) > 1 else "medium,large,xlarge").split(",")
CAP = sys.argv[2] if len(sys.argv) > 2 else "uncapped"
RESULTS = []
OUTFILE = os.path.join(OUT, f"results_maplib_memcap_{CAP}.json")
TIMEOUT = 1800

try:
    import psutil
    _PROC = psutil.Process(os.getpid())
except Exception:
    _PROC = None


class _Mem:
    def __init__(s, interval=0.1):
        s.interval = interval; s.peak = 0; s._stop = threading.Event(); s._t = None
    def _run(s):
        while not s._stop.is_set():
            if _PROC:
                try:
                    r = _PROC.memory_info().rss
                    if r > s.peak: s.peak = r
                except Exception: pass
            s._stop.wait(s.interval)
    def __enter__(s):
        if _PROC:
            s.peak = _PROC.memory_info().rss
            s._t = threading.Thread(target=s._run, daemon=True); s._t.start()
        return s
    def __exit__(s, *a):
        s._stop.set()
        if s._t: s._t.join(timeout=1.0)
    @property
    def peak_mb(s): return round(s.peak / 1048576, 1) if s.peak else None


class TO(Exception): pass
def _h(sig, frm): raise TO()


def save():
    os.makedirs(OUT, exist_ok=True)
    with open(OUTFILE, "w") as f:
        json.dump(RESULTS, f, indent=2)


def rec(scale, op, seconds, peak_mb=None):
    RESULTS.append({"framework": "maplib", "cap": CAP, "scale": scale,
                    "operation": op, "seconds": seconds, "peak_mb": peak_mb})
    save()  # persist after every op so an OOM-kill leaves a trace


def timed(label, fn, warmup=False, timeout=TIMEOUT):
    gc.collect()
    signal.signal(signal.SIGALRM, _h); signal.alarm(timeout)
    try:
        with _Mem() as m:
            t0 = time.perf_counter(); result = fn(); el = time.perf_counter() - t0
        signal.alarm(0)
        if not warmup:
            print(f"  {label}: {el:.4f}s  (peak {m.peak_mb} MB)", flush=True)
        return result, el, m.peak_mb
    except TO:
        signal.alarm(0); print(f"  {label}: TIMEOUT (>{timeout}s)", flush=True)
        return None, None, None


def load_query(name):
    with open(f"{QUERIES}/{name}.rq") as f:
        return f.read()


def run_scale(scale):
    print(f"\n{'='*60}\nmaplib (in-memory, cap={CAP}) — {scale}\n{'='*60}", flush=True)
    ttl = f"{DATA}/{scale}.ttl"; nt = f"{DATA}/{scale}.nt"
    if not os.path.exists(ttl):
        print(f"  {scale}: data not found, skipping", flush=True); return

    def read_ttl():
        m = Model(); m.read(ttl, parallel=True); return m
    m, t, pk = timed("Read Turtle", read_ttl)
    if t is None:
        rec(scale, "read_turtle", "TIMEOUT"); return
    rec(scale, "read_turtle", t, pk)
    try:
        cnt = m.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }", streaming=True)["c"][0]
        print(f"  Triple count: {cnt}", flush=True)
    except Exception as e:
        print(f"  count failed: {e}", flush=True)

    _, t, pk = timed("Write Turtle", lambda: m.write("/tmp/out.ttl", format="turtle"))
    rec(scale, "write_turtle", t if t is not None else "TIMEOUT", pk)
    _, t, pk = timed("Write N-Triples", lambda: m.write("/tmp/out.nt", format="ntriples"))
    rec(scale, "write_ntriples", t if t is not None else "TIMEOUT", pk)

    def read_nt():
        m2 = Model(); m2.read(nt, parallel=True); return m2
    _, t, pk = timed("Read N-Triples", read_nt)
    rec(scale, "read_ntriples", t if t is not None else "TIMEOUT", pk)

    print(f"  SPARQL queries ({scale}):", flush=True)
    for q in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        text = load_query(q)
        is_upd = any(l.strip().upper().startswith(("DELETE", "INSERT")) for l in text.split("\n") if not l.strip().upper().startswith("PREFIX"))
        is_con = any(l.strip().upper().startswith("CONSTRUCT") for l in text.split("\n"))
        def run(t=text, u=is_upd, c=is_con):
            return m.update(t) if u else (m.query(t) if c else m.query(t, streaming=True))
        _, t, pk = timed(f"  {q}", run, warmup=True)
        rec(scale, f"query_{q}", t if t is not None else "TIMEOUT", pk)
    del m; gc.collect()


if __name__ == "__main__":
    import importlib.metadata as md
    try: ver = md.version("maplib")
    except Exception: ver = "?"
    print(f"maplib {ver} — constrained-memory test, cap={CAP}, scales={SCALES}", flush=True)
    RESULTS.append({"framework": "maplib", "cap": CAP, "operation": "meta", "maplib_version": ver}); save()
    for sc in SCALES:
        try:
            run_scale(sc)
        except Exception as e:
            print(f"\n  ERROR on {sc}: {type(e).__name__}: {e}", flush=True)
            rec(sc, "error", str(e))
    print(f"\nDone. Results: {OUTFILE}", flush=True)
