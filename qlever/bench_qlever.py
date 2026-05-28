"""
Benchmark: QLever — index building and SPARQL queries via native binaries.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation (10 minutes for xlarge index build).

QLever is a high-performance SPARQL engine developed at the University of
Freiburg. Unlike in-memory libraries, it builds a persistent on-disk index
and serves queries through an HTTP endpoint.

I/O mapping:
  - read_turtle   → build index from Turtle file
  - read_ntriples → build index from N-Triples file
  - write_turtle / write_ntriples → N/A (QLever is a query engine, not
    a serialisation tool; these are recorded as "N/A")

Prerequisites:
  - qlever-index and qlever-server on PATH (e.g. brew install qlever)
"""

import time
import json
import os
import gc
import signal
import subprocess
import shutil
import urllib.request
import urllib.parse
import urllib.error

QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RESULTS = []
TIMEOUT = 600  # 10 minutes default
INDEX_TIMEOUT = 600  # 10 minutes for index building (xlarge)

QLEVER_PORT = 7019  # Use non-standard port to avoid conflicts

# Working directory for QLever index files (inside the qlever/ folder)
WORK_DIR = os.path.join(os.path.dirname(__file__), "qlever-workdir")

# Track the server process so we can stop it between scales
_server_proc = None


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


def stop_qlever():
    """Stop any running QLever server process."""
    global _server_proc
    if _server_proc is not None:
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
            _server_proc.wait(timeout=5)
        except Exception:
            pass
        _server_proc = None
    # Also kill any stray qlever-server on our port
    try:
        subprocess.run(
            ["pkill", "-f", f"qlever-server.*-p {QLEVER_PORT}"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass
    time.sleep(0.5)


def clean_workdir():
    """Remove the QLever index working directory."""
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR, exist_ok=True)


def build_index(data_file, input_format="turtle"):
    """
    Build a QLever index from the given data file using the native binary.
    """
    clean_workdir()

    fmt = "ttl" if input_format == "turtle" else "nt"

    # Write a minimal settings JSON
    settings = {
        "prefixes-external": [],
        "languages-internal": [],
        "ascii-prefixes-only": True,
        "num-triples-per-batch": 1000000,
    }
    settings_path = os.path.join(WORK_DIR, "settings.json")
    with open(settings_path, "w") as f:
        json.dump(settings, f)

    cmd = [
        "qlever-index",
        "-i", os.path.join(WORK_DIR, "index"),
        "-f", os.path.abspath(data_file),
        "-F", fmt,
        "-s", settings_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=INDEX_TIMEOUT,
            cwd=WORK_DIR,
        )
    except subprocess.TimeoutExpired:
        print(f"    Index build timed out (>{INDEX_TIMEOUT}s)")
        return False

    if result.returncode != 0:
        print(f"    Index build failed (rc={result.returncode})")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-10:]:
                print(f"      {line}")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-5:]:
                print(f"      [stdout] {line}")
        return False

    # Verify index files were created
    index_files = [f for f in os.listdir(WORK_DIR) if f.startswith("index.")]
    if not index_files:
        print(f"    No index files found in workdir")
        return False

    print(f"    Index built: {len(index_files)} files")
    return True


def start_server():
    """Start the QLever server as a native background process."""
    global _server_proc
    stop_qlever()

    cmd = [
        "qlever-server",
        "-i", os.path.join(WORK_DIR, "index"),
        "-p", str(QLEVER_PORT),
    ]

    _server_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=WORK_DIR,
    )

    print(f"    Server started (PID {_server_proc.pid}), waiting for endpoint...")

    # Wait for the server to be ready (poll the endpoint)
    endpoint = f"http://localhost:{QLEVER_PORT}"
    for attempt in range(60):  # up to 60 seconds
        time.sleep(1)

        # Check if process is still alive
        if _server_proc.poll() is not None:
            stdout = _server_proc.stdout.read().decode("utf-8", errors="replace")
            stderr = _server_proc.stderr.read().decode("utf-8", errors="replace")
            print(f"    Server exited unexpectedly (rc={_server_proc.returncode})")
            if stderr:
                for line in stderr.strip().split("\n")[-10:]:
                    print(f"      {line}")
            if stdout:
                for line in stdout.strip().split("\n")[-5:]:
                    print(f"      [stdout] {line}")
            _server_proc = None
            return False

        try:
            test_query = urllib.parse.urlencode({"query": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"}).encode("utf-8")
            req = urllib.request.Request(endpoint, data=test_query,
                                        headers={"Accept": "application/sparql-results+json"})
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                print(f"    Server ready (took {attempt + 1}s)")
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, OSError) as e:
            if attempt % 10 == 9:
                print(f"    Still waiting... ({attempt + 1}s) — {e}")

    print(f"    Server did not become ready within 60 seconds")
    stop_qlever()
    return False


def _is_construct(query_text):
    """Check if a SPARQL query is a CONSTRUCT query."""
    return any(line.strip().upper().startswith("CONSTRUCT") for line in query_text.split("\n"))


def _is_update(query_text):
    """Check if a SPARQL query is an UPDATE (DELETE/INSERT) query."""
    for line in query_text.split("\n"):
        stripped = line.strip().upper()
        if stripped.startswith("DELETE") or stripped.startswith("INSERT"):
            return True
    return False


# Queries that QLever cannot run (read-only engine, no SPARQL Update support)
UPDATE_QUERIES = {"q6_delete_insert"}


def sparql_query(query_text):
    """
    Execute a SPARQL query against the running QLever server.
    Returns the JSON result (SELECT) or raw text (CONSTRUCT).
    """
    endpoint = f"http://localhost:{QLEVER_PORT}"
    data = urllib.parse.urlencode({"query": query_text}).encode("utf-8")
    if _is_construct(query_text):
        headers = {"Accept": "text/turtle"}
    else:
        headers = {"Accept": "application/sparql-results+json"}

    req = urllib.request.Request(endpoint, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
        if _is_construct(query_text):
            return body  # raw Turtle text
        return json.loads(body)


def bench_io(scale, ttl_path, nt_path):
    """
    Benchmark index building for a given scale.

    For QLever, "reading" means building the index — this is the
    equivalent of loading data into an in-memory store.
    """
    print(f"\n{'='*60}")
    print(f"QLever (native) — {scale} dataset")
    print(f"{'='*60}")

    index_timeout = INDEX_TIMEOUT if scale == "xlarge" else TIMEOUT

    # --- Build index from Turtle (= "Read Turtle") ---
    def build_ttl():
        success = build_index(ttl_path, input_format="turtle")
        if not success:
            raise RuntimeError("Index build failed")
        return success
    _, t_read_ttl = timed("Build index (Turtle)", build_ttl, timeout=index_timeout)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "qlever", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
    else:
        RESULTS.append({"framework": "qlever", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})

    # --- Write Turtle: N/A for QLever ---
    RESULTS.append({"framework": "qlever", "scale": scale, "operation": "write_turtle", "seconds": "N/A"})
    print("  Write Turtle: N/A (QLever is a query engine)")

    # --- Write N-Triples: N/A for QLever ---
    RESULTS.append({"framework": "qlever", "scale": scale, "operation": "write_ntriples", "seconds": "N/A"})
    print("  Write N-Triples: N/A (QLever is a query engine)")

    # --- Build index from N-Triples (= "Read N-Triples") ---
    def build_nt():
        success = build_index(nt_path, input_format="ntriples")
        if not success:
            raise RuntimeError("Index build failed")
        return success
    _, t_read_nt = timed("Build index (N-Triples)", build_nt, timeout=index_timeout)
    if t_read_nt is not None:
        RESULTS.append({"framework": "qlever", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "qlever", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

    # Start server from the last built index (N-Triples) for query benchmarks
    print("\n  Starting QLever server...")
    if not start_server():
        print("  Failed to start server — skipping queries")
        return None

    # Quick sanity check: count triples
    try:
        result = sparql_query("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o . }")
        count = result["results"]["bindings"][0]["count"]["value"]
        print(f"  Triple count: {count}")
    except Exception as e:
        print(f"  Warning: triple count check failed: {e}")

    return True  # server is running


def bench_queries(server_ready, scale):
    """Benchmark SPARQL queries against the running QLever server."""
    if not server_ready:
        print(f"\n  Skipping queries ({scale}) — server not running")
        for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}_cold", "seconds": "TIMEOUT"})
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        # Skip UPDATE queries — QLever is a read-only engine
        if qname in UPDATE_QUERIES:
            print(f"    {qname}: N/A (QLever is read-only, no SPARQL Update support)")
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": "N/A"})
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}_cold", "seconds": "N/A"})
            continue

        q = load_query(qname)

        # Warmup run (also recorded as cold timing)
        _, t_warmup = timed(f"  {qname} (warmup)", lambda: sparql_query(q), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}_cold", "seconds": "TIMEOUT"})
            continue
        RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}_cold", "seconds": t_warmup})

        # Best of 3
        times = []
        for _ in range(3):
            _, t = timed(f"  {qname}", lambda: sparql_query(q), warmup=True)
            if t is not None:
                times.append(t)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


if __name__ == "__main__":
    # Verify native binaries are available
    for binary in ["qlever-index", "qlever-server"]:
        if shutil.which(binary) is None:
            print(f"ERROR: '{binary}' not found on PATH.")
            print("  Install with: brew install qlever")
            print(f"  Or check: which {binary}")
            exit(1)

    # Show version info
    try:
        result = subprocess.run(["qlever-index", "--help"], capture_output=True, text=True, timeout=5)
        # First line often contains version
        first_line = (result.stdout or result.stderr or "").strip().split("\n")[0]
        print(f"  qlever-index: {first_line}")
    except Exception:
        pass

    print("QLever benchmark starting (native binaries)...")
    print(f"  Port: {QLEVER_PORT}")

    def save_results():
        results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, "results_qlever.json"), "w") as f:
            json.dump(RESULTS, f, indent=2)
        print(f"\nResults saved to results/results_qlever.json ({len(RESULTS)} entries)")

    for scale in ["medium", "large", "xlarge"]:
        ttl_path = os.path.join(DATA_DIR, f"{scale}.ttl")
        nt_path = os.path.join(DATA_DIR, f"{scale}.nt")

        if not os.path.exists(ttl_path):
            print(f"\n  Skipping {scale} — {ttl_path} not found")
            continue

        try:
            server_ready = bench_io(scale, ttl_path, nt_path)
            bench_queries(server_ready, scale)
        except Exception as e:
            print(f"\n  ERROR on {scale}: {e}")
            print("  Saving partial results and continuing...")
        finally:
            stop_qlever()
            save_results()
            gc.collect()

    # Final cleanup
    stop_qlever()
    clean_workdir()
    save_results()
