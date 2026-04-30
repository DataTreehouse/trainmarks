"""
Benchmark: Virtuoso Open-Source — bulk loading and SPARQL queries via Docker.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation (10 minutes for xlarge loading).

Virtuoso is a high-performance hybrid (relational + RDF) database engine
developed by OpenLink Software. It is one of the most widely deployed SPARQL
endpoints in the world (e.g. DBpedia).

I/O mapping:
  - read_turtle   → bulk-load Turtle file via isql + rdf_loader_run()
  - read_ntriples → bulk-load N-Triples file via isql + rdf_loader_run()
  - write_turtle / write_ntriples → N/A (Virtuoso is a database server,
    not a serialisation tool; these are recorded as "N/A")

Prerequisites:
  - Docker installed and running
  - Image: docker pull openlink/virtuoso-opensource-7:latest
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
TIMEOUT = 600       # 10 minutes default
LOAD_TIMEOUT = 600  # 10 minutes for bulk loading (xlarge)

VIRTUOSO_IMAGE = "openlink/virtuoso-opensource-7:latest"
VIRTUOSO_HTTP_PORT = 8891   # Non-standard to avoid conflicts
VIRTUOSO_ISQL_PORT = 1112   # Non-standard to avoid conflicts
CONTAINER_NAME = "virtuoso-bench"
DBA_PASSWORD = "benchpass"
GRAPH_IRI = "http://benchmark.example/graph"

# Working directory for Virtuoso database files
WORK_DIR = os.path.join(os.path.dirname(__file__), "virtuoso-workdir")


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


def stop_virtuoso():
    """Stop and remove any running Virtuoso benchmark container."""
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        timeout=30,
    )
    time.sleep(2)


def clean_workdir():
    """Remove and recreate the Virtuoso working directory."""
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(os.path.join(WORK_DIR, "import"), exist_ok=True)


def isql(sql, timeout=TIMEOUT):
    """Execute a SQL command via isql inside the running container."""
    cmd = [
        "docker", "exec", CONTAINER_NAME,
        "isql", "localhost:1111", "dba", DBA_PASSWORD,
        "EXEC=" + sql,
    ]
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


def start_virtuoso(scale):
    """Start a fresh Virtuoso container with tuned buffers."""
    stop_virtuoso()
    clean_workdir()

    # Tune buffers based on dataset scale
    # Each buffer = 8 KB, so 170000 buffers ≈ 1.3 GB
    if scale == "xlarge":
        num_buffers = 340000
        max_dirty = 250000
    elif scale == "large":
        num_buffers = 170000
        max_dirty = 130000
    else:
        num_buffers = 85000
        max_dirty = 65000

    rc, stdout, stderr = docker_run([
        "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{VIRTUOSO_HTTP_PORT}:8890",
        "-p", f"{VIRTUOSO_ISQL_PORT}:1111",
        "-e", f"DBA_PASSWORD={DBA_PASSWORD}",
        "-e", f"VIRT_Parameters_NumberOfBuffers={num_buffers}",
        "-e", f"VIRT_Parameters_MaxDirtyBuffers={max_dirty}",
        "-e", "VIRT_Parameters_DirsAllowed=., /data, /opt/virtuoso-opensource/vad",
        "-v", f"{os.path.abspath(DATA_DIR)}:/data",
        VIRTUOSO_IMAGE,
    ], timeout=60)

    if rc != 0:
        print(f"    Container start failed: {stderr}")
        return False

    # Wait for Virtuoso to be ready (poll isql)
    print("  Waiting for Virtuoso to start...")
    for attempt in range(60):
        time.sleep(1)
        rc, stdout, _ = isql("SELECT 1;", timeout=5)
        if rc == 0 and "1" in stdout:
            print(f"  Virtuoso ready (took {attempt + 1}s)")
            return True

    print("  Virtuoso did not become ready within 60 seconds")
    return False


def bulk_load(data_file, input_format="turtle"):
    """
    Bulk-load a data file into Virtuoso.
    The data directory is mounted directly at /data in the container,
    so we just point ld_dir at the specific file.
    """
    basename = os.path.basename(data_file)

    # Clear any existing data in the graph
    isql(f"SPARQL CLEAR GRAPH <{GRAPH_IRI}>;", timeout=60)

    # Clear the load list
    isql("DELETE FROM DB.DBA.load_list;", timeout=30)

    # Register the specific file for loading
    rc, stdout, stderr = isql(f"ld_dir('/data', '{basename}', '{GRAPH_IRI}');", timeout=30)
    if rc != 0:
        print(f"    ld_dir failed: {stderr}")
        return False

    # Check the load list to verify file was registered
    rc, stdout, _ = isql("SELECT COUNT(*) FROM DB.DBA.load_list;", timeout=10)
    print(f"    Load list: {stdout.strip()}")

    # Run the loader (this is what we time)
    rc, stdout, stderr = isql("rdf_loader_run();", timeout=LOAD_TIMEOUT)
    if rc != 0:
        print(f"    rdf_loader_run failed: {stderr}")
        return False

    # Checkpoint to persist
    isql("checkpoint;", timeout=60)

    return True


def sparql_query(query_text):
    """Execute a SPARQL query against the running Virtuoso endpoint."""
    endpoint = f"http://localhost:{VIRTUOSO_HTTP_PORT}/sparql"
    params = urllib.parse.urlencode({
        "query": query_text,
        "default-graph-uri": GRAPH_IRI,
        "format": "application/sparql-results+json",
    }).encode("utf-8")

    req = urllib.request.Request(endpoint, data=params)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bench_io(scale, ttl_path, nt_path):
    """
    Benchmark bulk loading for a given scale.
    For Virtuoso, "reading" means bulk-loading data — the equivalent
    of loading data into an in-memory store.
    """
    print(f"\n{'='*60}")
    print(f"Virtuoso — {scale} dataset")
    print(f"{'='*60}")

    load_timeout = LOAD_TIMEOUT if scale == "xlarge" else TIMEOUT

    # --- Start a fresh Virtuoso instance ---
    if not start_virtuoso(scale):
        print("  Failed to start Virtuoso — skipping this scale")
        return None

    # --- Bulk load Turtle (= "Read Turtle") ---
    def load_ttl():
        success = bulk_load(ttl_path, input_format="turtle")
        if not success:
            raise RuntimeError("Bulk load failed")
        return success
    _, t_read_ttl = timed("Bulk load (Turtle)", load_ttl, timeout=load_timeout)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
    else:
        RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})

    # --- Write Turtle: N/A ---
    RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": "write_turtle", "seconds": "N/A"})
    print("  Write Turtle: N/A (Virtuoso is a database server)")

    # --- Write N-Triples: N/A ---
    RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": "write_ntriples", "seconds": "N/A"})
    print("  Write N-Triples: N/A (Virtuoso is a database server)")

    # --- Bulk load N-Triples (= "Read N-Triples") ---
    def load_nt():
        success = bulk_load(nt_path, input_format="ntriples")
        if not success:
            raise RuntimeError("Bulk load failed")
        return success
    _, t_read_nt = timed("Bulk load (N-Triples)", load_nt, timeout=load_timeout)
    if t_read_nt is not None:
        RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

    # Verify triple count
    try:
        result = sparql_query(f"SELECT (COUNT(*) AS ?count) WHERE {{ ?s ?p ?o . }}")
        count = result["results"]["bindings"][0]["count"]["value"]
        print(f"  Triple count: {count}")
    except Exception as e:
        print(f"  Warning: triple count check failed: {e}")

    return True  # server is running


def bench_queries(server_ready, scale):
    """Benchmark SPARQL queries against the running Virtuoso endpoint."""
    if not server_ready:
        print(f"\n  Skipping queries ({scale}) — server not running")
        for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
            RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
        return

    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
        q = load_query(qname)

        # Warmup run
        _, t_warmup = timed(f"  {qname} (warmup)", lambda q=q: sparql_query(q), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
            continue

        # Best of 3
        times = []
        for _ in range(3):
            _, t = timed(f"  {qname}", lambda q=q: sparql_query(q), warmup=True)
            if t is not None:
                times.append(t)
        if times:
            best = min(times)
            print(f"    {qname}: {best:.4f}s (best of 3)")
            RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "virtuoso", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


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

    # Check if Virtuoso image is available
    rc, stdout, _ = docker_run(["images", "-q", VIRTUOSO_IMAGE.split(":")[0]])
    if not stdout.strip():
        print(f"Pulling Virtuoso Docker image ({VIRTUOSO_IMAGE})...")
        docker_run(["pull", VIRTUOSO_IMAGE], timeout=600)

    print("Virtuoso benchmark starting...")
    print(f"  Image:  {VIRTUOSO_IMAGE}")
    print(f"  Ports:  HTTP={VIRTUOSO_HTTP_PORT}, ISQL={VIRTUOSO_ISQL_PORT}")

    def save_results():
        results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, "results_virtuoso.json"), "w") as f:
            json.dump(RESULTS, f, indent=2)
        print(f"\nResults saved to results/results_virtuoso.json ({len(RESULTS)} entries)")

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
            # Clean up between scales and save partial results
            stop_virtuoso()
            save_results()
            gc.collect()

    # Final cleanup
    stop_virtuoso()
    save_results()
