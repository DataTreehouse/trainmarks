"""
Benchmark: GraphDB — index building and SPARQL queries via Docker.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation (10 minutes for xlarge loading).

GraphDB is Ontotext's enterprise-grade RDF triplestore built on RDF4J.
It runs as a Java-based server with a SPARQL endpoint.

I/O mapping:
  - read_turtle   → create repo + server-side import of Turtle file
  - read_ntriples → create repo + server-side import of N-Triples file
  - write_turtle / write_ntriples → N/A (GraphDB is a database server)

Prerequisites:
  - Docker installed and running
  - GraphDB Docker image: docker pull ontotext/graphdb:10.8.0
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
LOAD_TIMEOUT = 600  # 10 minutes for large imports

GRAPHDB_IMAGE = "ontotext/graphdb:10.8.0"
GRAPHDB_PORT = 7200
CONTAINER_NAME = "graphdb-bench"
REPO_NAME = "benchmark"


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
    """Run a Docker command with timeout."""
    cmd = ["docker"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def stop_graphdb():
    """Stop and remove any running GraphDB benchmark container."""
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=30)
    time.sleep(1)


def start_graphdb():
    """Start a fresh GraphDB container with data directory mounted for server-side import."""
    stop_graphdb()

    rc, stdout, stderr = docker_run([
        "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{GRAPHDB_PORT}:{GRAPHDB_PORT}",
        "-v", f"{os.path.abspath(DATA_DIR)}:/root/graphdb-import",
        "-e", "GDB_JAVA_OPTS=-Xms4g -Xmx4g",
        GRAPHDB_IMAGE,
    ])

    if rc != 0:
        print(f"    Container start failed: {stderr}")
        return False

    print(f"    Container started, waiting for GraphDB to be ready...")

    # Wait for GraphDB to be ready (poll the REST API)
    for attempt in range(120):  # up to 120 seconds (GraphDB/Java can be slow to start)
        time.sleep(1)

        # Check container is running
        rc2, out2, _ = docker_run(["inspect", "--format", "{{.State.Running}}", CONTAINER_NAME], timeout=5)
        if rc2 != 0 or "false" in out2.lower():
            _, logs, _ = docker_run(["logs", "--tail", "20", CONTAINER_NAME], timeout=5)
            print(f"    Container exited unexpectedly. Logs:")
            print(logs)
            return False

        try:
            req = urllib.request.Request(
                f"http://localhost:{GRAPHDB_PORT}/rest/repositories",
                headers={"Accept": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                print(f"    GraphDB ready (took {attempt + 1}s)")
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, OSError):
            if attempt % 15 == 14:
                print(f"    Still waiting... ({attempt + 1}s)")

    print("    GraphDB did not become ready within 120 seconds")
    return False


def create_repository():
    """Create a fresh repository via the REST API using a config.ttl file."""
    # First, delete existing repo if any
    try:
        req = urllib.request.Request(
            f"http://localhost:{GRAPHDB_PORT}/rest/repositories/{REPO_NAME}",
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=30)
        time.sleep(1)
    except (urllib.error.URLError, urllib.error.HTTPError):
        pass  # repo didn't exist, that's fine

    # Write a config.ttl for a free repository
    config = f"""
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rep: <http://www.openrdf.org/config/repository#> .
@prefix sr: <http://www.openrdf.org/config/repository/sail#> .
@prefix sail: <http://www.openrdf.org/config/sail#> .
@prefix graphdb: <http://www.ontotext.com/config/graphdb#> .

[] a rep:Repository ;
    rep:repositoryID "{REPO_NAME}" ;
    rdfs:label "Benchmark repository" ;
    rep:repositoryImpl [
        rep:repositoryType "graphdb:SailRepository" ;
        sr:sailImpl [
            sail:sailType "graphdb:Sail" ;
            graphdb:read-only "false" ;
            graphdb:ruleset "empty" ;
            graphdb:storage-folder "storage" ;
            graphdb:enable-context-index "true" ;
            graphdb:enablePredicateList "false" ;
            graphdb:enable-fts-index "false" ;
            graphdb:fts-indexes ("default" "iri") ;
            graphdb:entity-index-size "10000000" ;
            graphdb:in-memory-literal-properties "false" ;
            graphdb:check-for-inconsistencies "false" ;
        ]
    ] .
"""
    config_path = os.path.join(os.path.dirname(__file__), "repo-config.ttl")
    with open(config_path, "w") as f:
        f.write(config)

    # Create repo via REST API using multipart form upload
    import http.client
    import mimetypes

    boundary = "----BenchmarkBoundary"
    with open(config_path, "rb") as f:
        config_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="config"; filename="repo-config.ttl"\r\n'
        f"Content-Type: text/turtle\r\n\r\n"
    ).encode() + config_data + f"\r\n--{boundary}--\r\n".encode()

    conn = http.client.HTTPConnection("localhost", GRAPHDB_PORT, timeout=30)
    conn.request(
        "POST",
        "/rest/repositories",
        body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    resp_body = resp.read()
    conn.close()

    if resp.status in (200, 201, 204):
        print(f"    Repository '{REPO_NAME}' created")
        return True
    else:
        print(f"    Repository creation failed: {resp.status} {resp_body.decode()}")
        return False


def server_import(filename):
    """
    Trigger server-side import of a file already visible in /root/graphdb-import.
    This is much faster than streaming via HTTP POST for large files.

    Polls the import status API until the file shows status=DONE with
    addedStatements > 0 (confirming data was actually loaded).
    """
    payload = json.dumps({"fileNames": [filename]}).encode("utf-8")
    req = urllib.request.Request(
        f"http://localhost:{GRAPHDB_PORT}/rest/repositories/{REPO_NAME}/import/server",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=30)
    if resp.status not in (200, 201, 202, 204):
        raise RuntimeError(f"Import trigger failed: {resp.status}")

    # Poll until our file reaches DONE with addedStatements > 0
    status_url = f"http://localhost:{GRAPHDB_PORT}/rest/repositories/{REPO_NAME}/import/server"

    for attempt in range(LOAD_TIMEOUT):
        time.sleep(1)
        try:
            req = urllib.request.Request(status_url, headers={"Accept": "application/json"})
            resp = urllib.request.urlopen(req, timeout=10)
            status_data = json.loads(resp.read().decode("utf-8"))

            for task in status_data:
                name = task.get("name", "")
                status = task.get("status", "")
                added = task.get("addedStatements", 0)

                if name == filename:
                    if attempt == 0:
                        print(f"    Import status: {name}={status} (added={added})")

                    if status == "DONE" and added > 0:
                        print(f"    Import complete: {added} statements added")
                        return True
                    elif status == "DONE" and added == 0:
                        # DONE but nothing loaded — keep polling briefly
                        # in case addedStatements updates with a lag
                        if attempt > 5:
                            raise RuntimeError(
                                f"Import reports DONE but 0 statements added for {filename}"
                            )
                    elif status == "ERROR":
                        msg = task.get("message", "unknown error")
                        raise RuntimeError(f"Import error for {filename}: {msg}")
                    # else: IMPORTING / PENDING / NONE → keep polling

            if attempt % 30 == 29:
                summary = [f"{t.get('name','')}={t.get('status','')}({t.get('addedStatements',0)})"
                           for t in status_data if filename in t.get('name', '')]
                print(f"    Still importing... ({attempt + 1}s) {summary}")

        except (urllib.error.URLError, ConnectionError, OSError) as e:
            if attempt % 15 == 14:
                print(f"    Polling error ({attempt + 1}s): {e}")

    raise RuntimeError(f"Import of {filename} did not complete within {LOAD_TIMEOUT}s")


def delete_repository():
    """Delete the benchmark repository to free resources."""
    try:
        req = urllib.request.Request(
            f"http://localhost:{GRAPHDB_PORT}/rest/repositories/{REPO_NAME}",
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=30)
        time.sleep(1)
    except (urllib.error.URLError, urllib.error.HTTPError):
        pass


def sparql_query(query_text):
    """Execute a SPARQL query against the running GraphDB server."""
    endpoint = f"http://localhost:{GRAPHDB_PORT}/repositories/{REPO_NAME}"
    data = urllib.parse.urlencode({"query": query_text}).encode("utf-8")
    headers = {"Accept": "application/sparql-results+json"}

    req = urllib.request.Request(endpoint, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bench_io(scale, ttl_path, nt_path):
    """Benchmark loading for a given scale."""
    print(f"\n{'='*60}")
    print(f"GraphDB — {scale} dataset")
    print(f"{'='*60}")

    load_timeout = LOAD_TIMEOUT if scale == "xlarge" else TIMEOUT

    ttl_basename = os.path.basename(ttl_path)
    nt_basename = os.path.basename(nt_path)

    # --- Load Turtle (= "Read Turtle") ---
    def load_ttl():
        delete_repository()
        if not create_repository():
            raise RuntimeError("Repository creation failed")
        server_import(ttl_basename)
        return True

    _, t_read_ttl = timed("Load Turtle (server import)", load_ttl, timeout=load_timeout)
    if t_read_ttl is not None:
        RESULTS.append({"framework": "graphdb", "scale": scale, "operation": "read_turtle", "seconds": t_read_ttl})
    else:
        RESULTS.append({"framework": "graphdb", "scale": scale, "operation": "read_turtle", "seconds": "TIMEOUT"})

    # --- Write Turtle: N/A for GraphDB ---
    RESULTS.append({"framework": "graphdb", "scale": scale, "operation": "write_turtle", "seconds": "N/A"})
    print("  Write Turtle: N/A (GraphDB is a database server)")

    # --- Write N-Triples: N/A for GraphDB ---
    RESULTS.append({"framework": "graphdb", "scale": scale, "operation": "write_ntriples", "seconds": "N/A"})
    print("  Write N-Triples: N/A (GraphDB is a database server)")

    # --- Load N-Triples (= "Read N-Triples") ---
    def load_nt():
        delete_repository()
        if not create_repository():
            raise RuntimeError("Repository creation failed")
        server_import(nt_basename)
        return True

    _, t_read_nt = timed("Load N-Triples (server import)", load_nt, timeout=load_timeout)
    if t_read_nt is not None:
        RESULTS.append({"framework": "graphdb", "scale": scale, "operation": "read_ntriples", "seconds": t_read_nt})
    else:
        RESULTS.append({"framework": "graphdb", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT"})

    # Sanity check: verify triple count matches expected values
    EXPECTED_TRIPLES = {"medium": 98_000, "large": 1_001_000, "xlarge": 9_995_000}
    try:
        result = sparql_query("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o . }")
        count = int(result["results"]["bindings"][0]["count"]["value"])
        expected = EXPECTED_TRIPLES.get(scale, 0)
        print(f"  Triple count: {count} (expected ~{expected})")
        if expected > 0 and count < expected * 0.9:
            print(f"  WARNING: triple count {count} is significantly below expected {expected}!")
            print(f"  Data likely failed to load — marking I/O as FAILED, skipping queries.")
            # Overwrite the read results with FAILED
            for r in RESULTS:
                if r["framework"] == "graphdb" and r["scale"] == scale and r["operation"].startswith("read_"):
                    r["seconds"] = "FAILED"
            return False  # signal to skip queries
    except Exception as e:
        print(f"  Warning: triple count check failed: {e}")

    return True  # server is running with N-Triples data loaded


def bench_queries(server_ready, scale):
    """Benchmark SPARQL queries against the running GraphDB server."""
    if not server_ready:
        print(f"\n  Skipping queries ({scale}) — server not running")
        for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
            RESULTS.append({"framework": "graphdb", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
        return
    print(f"\n  SPARQL queries ({scale}):")

    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
        q = load_query(qname)

        # Warmup run
        _, t_warmup = timed(f"  {qname} (warmup)", lambda: sparql_query(q), warmup=True)
        if t_warmup is None:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "graphdb", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})
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
            RESULTS.append({"framework": "graphdb", "scale": scale, "operation": f"query_{qname}", "seconds": best})
        else:
            print(f"    {qname}: TIMEOUT")
            RESULTS.append({"framework": "graphdb", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT"})


def save_results():
    """Save results incrementally."""
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "results_graphdb.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"  Results saved ({len(RESULTS)} entries)")


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

    # Check if GraphDB image is available
    rc, stdout, _ = docker_run(["images", "-q", GRAPHDB_IMAGE])
    if not stdout.strip():
        print(f"Pulling GraphDB Docker image ({GRAPHDB_IMAGE})...")
        docker_run(["pull", GRAPHDB_IMAGE], timeout=600)

    print("GraphDB benchmark starting...")
    print(f"  Image:  {GRAPHDB_IMAGE}")
    print(f"  Port:   {GRAPHDB_PORT}")

    # Start GraphDB once — it stays running for all scales
    if not start_graphdb():
        print("ERROR: Could not start GraphDB. Exiting.")
        exit(1)

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
            save_results()
            gc.collect()

    # Final cleanup
    stop_graphdb()
    save_results()
