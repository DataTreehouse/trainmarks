"""
Benchmark: QLever — index building and SPARQL queries via Docker.
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
  - Docker installed and running
  - QLever Docker image: docker pull adfreiburg/qlever
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

QLEVER_IMAGE = "adfreiburg/qlever"
QLEVER_PORT = 7019  # Use non-standard port to avoid conflicts
CONTAINER_NAME = "qlever-bench"

# Working directory for QLever index files (inside the qlever/ folder)
WORK_DIR = os.path.join(os.path.dirname(__file__), "qlever-workdir")


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


def docker_run(args, timeout=TIMEOUT):
    """Run a Docker command with timeout. Returns (returncode, stdout, stderr)."""
    cmd = ["docker"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def stop_qlever():
    """Stop and remove any running QLever benchmark container."""
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        timeout=30,
    )
    # Brief pause to let the port free up
    time.sleep(1)


def clean_workdir():
    """Remove the QLever index working directory."""
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR, exist_ok=True)


def build_index(data_file, input_format="turtle"):
    """
    Build a QLever index from the given data file.

    Uses the qlever CLI inside the Docker image. The data directory is
    mounted at /input and the workdir at /data (QLever's expected working dir).
    """
    clean_workdir()

    basename = os.path.basename(data_file)
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

    # Bypass the entrypoint and call qlever-index directly
    rc, stdout, stderr = docker_run([
        "run", "--rm",
        "--entrypoint", "/qlever/qlever-index",
        "-v", f"{os.path.abspath(DATA_DIR)}:/input:ro",
        "-v", f"{os.path.abspath(WORK_DIR)}:/data",
        "-w", "/data",
        "--name", f"{CONTAINER_NAME}-index",
        QLEVER_IMAGE,
        "-i", "/data/index",
        "-f", f"/input/{basename}",
        "-F", fmt,
        "-s", "/data/settings.json",
    ], timeout=INDEX_TIMEOUT)

    if rc != 0:
        print(f"    Index build failed (rc={rc})")
        if stderr:
            lines = stderr.strip().split("\n")
            for line in lines[-10:]:
                print(f"      {line}")
        if stdout:
            lines = stdout.strip().split("\n")
            for line in lines[-5:]:
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
    """Start the QLever server in a Docker container."""
    stop_qlever()

    # Bypass the entrypoint and call qlever-server directly as root
    # (index files were created as root by the index builder)
    rc, stdout, stderr = docker_run([
        "run", "-d",
        "--entrypoint", "/qlever/qlever-server",
        "--user", "root",
        "--name", CONTAINER_NAME,
        "-p", f"{QLEVER_PORT}:{QLEVER_PORT}",
        "-v", f"{os.path.abspath(WORK_DIR)}:/data",
        "-w", "/data",
        QLEVER_IMAGE,
        "-i", "/data/index",
        "-p", str(QLEVER_PORT),
    ])

    if rc != 0:
        print(f"    Server start failed: {stderr}")
        return False

    print(f"    Container started, waiting for endpoint...")

    # Wait for the server to be ready (poll the endpoint)
    endpoint = f"http://localhost:{QLEVER_PORT}"
    for attempt in range(60):  # up to 60 seconds
        time.sleep(1)

        # First check if container is still running
        rc2, out2, _ = docker_run(["inspect", "--format", "{{.State.Running}}", CONTAINER_NAME], timeout=5)
        if rc2 != 0 or "false" in out2.lower():
            # Container exited — grab logs
            _, logs, _ = docker_run(["logs", "--tail", "20", CONTAINER_NAME], timeout=5)
            _, logs_err, _ = docker_run(["logs", "--tail", "20", CONTAINER_NAME], timeout=5)
            print(f"    Container exited unexpectedly. Logs:")
            print(logs)
            return False

        try:
            # Send a simple SPARQL query to check readiness
            # (bare GET to root may not return 200 on QLever)
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

    # Final check — dump logs
    _, logs, _ = docker_run(["logs", "--tail", "20", CONTAINER_NAME], timeout=5)
    print(f"    Server did not become ready within 60 seconds. Logs:")
    print(logs)
    return False


def sparql_query(query_text):
    """
    Execute a SPARQL query against the running QLever server.
    Returns the JSON result.
    """
    endpoint = f"http://localhost:{QLEVER_PORT}"
    data = urllib.parse.urlencode({"query": query_text}).encode("utf-8")
    headers = {"Accept": "application/sparql-results+json"}

    req = urllib.request.Request(endpoint, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bench_io(scale, ttl_path, nt_path):
    """
    Benchmark index building for a given scale.

    For QLever, "reading" means building the index — this is the
    equivalent of loading data into an in-memory store.
    """
    print(f"\n{'='*60}")
    print(f"QLever — {scale} dataset")
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
        for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
        q = load_query(qname)

        # Warmup run
        _, t_warmup = timed(f"  {qname} (warmup)", lambda: sparql_query(q), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "qlever", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            continue

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
    # Verify Docker is available
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=60, check=True)
    except subprocess.TimeoutExpired:
        print("ERROR: Docker is slow to respond. Is Docker Desktop fully started?")
        exit(1)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Docker is not available. Please install and start Docker.")
        exit(1)

    # Check if QLever image is available
    rc, stdout, _ = docker_run(["images", "-q", QLEVER_IMAGE])
    if not stdout.strip():
        print(f"Pulling QLever Docker image ({QLEVER_IMAGE})...")
        docker_run(["pull", QLEVER_IMAGE], timeout=600)

    print("QLever benchmark starting...")
    print(f"  Image:  {QLEVER_IMAGE}")
    print(f"  Port:   {QLEVER_PORT}")

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
