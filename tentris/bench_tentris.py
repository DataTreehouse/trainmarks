"""
Benchmark: TentrisDB — index build (load) and SPARQL queries via Docker.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.

Tentris is a tensor-based, disk-based RDF triplestore (dice-group / Tentris GmbH).

⚠️  CAVEATS — read before trusting these numbers:
  * Tentris is currently BETA (latest release ~v0.22.x, no 1.0 yet).
  * The native engine is Linux-only (glibc >= 2.34). On Apple silicon this image
    runs under linux/amd64 EMULATION (qemu), so timings are NOT directly
    comparable to the natively-running engines. Treat as indicative only.
  * Runs in the free (non-commercial) mode — no license file mounted.

I/O mapping:
  - read_ntriples → server load of the N-Triples shard (via TENTRIS_RDF_FILE on
    container init), timed from container start until the endpoint answers the
    expected COUNT. Includes container/server startup overhead (noted).
  - read_turtle / write_* → N/A (server; loads N-Triples on init here).

Records peak container memory (MB) per scale via docker stats.
"""

import time
import json
import os
import gc
import signal
import subprocess
import shutil
import tempfile
import urllib.request
import urllib.parse
import urllib.error
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from docker_mem import ContainerMemSampler  # noqa: E402

QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RESULTS = []
TIMEOUT = 600
LOAD_TIMEOUT = 1800  # emulated container + HTTP upload can be slow
STORAGE_BASE = os.path.join(os.path.dirname(__file__), "tentris-storage")

TENTRIS_IMAGE = "ghcr.io/tentris/tentris:latest"
TENTRIS_PORT = 9080
CONTAINER_NAME = "tentris-bench"
MEM = ContainerMemSampler(CONTAINER_NAME)

EXPECTED_TRIPLES = {"medium": 98_000, "large": 1_001_000, "xlarge": 9_995_000}
# Tentris is read-only over SPARQL query here; SPARQL Update is treated as N/A.
UPDATE_QUERIES = {"q6_delete_insert"}


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")


def timed(label, fn, warmup=False, timeout=TIMEOUT):
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
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def stop_tentris():
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=30)
    time.sleep(1)


def sparql_query(query_text):
    """Run a SPARQL query over HTTP. Endpoint path may need adjusting per Tentris build."""
    is_construct = any(l.strip().upper().startswith("CONSTRUCT") for l in query_text.split("\n"))
    endpoint = f"http://localhost:{TENTRIS_PORT}/sparql"
    data = urllib.parse.urlencode({"query": query_text}).encode("utf-8")
    headers = {"Accept": "text/turtle" if is_construct else "application/sparql-results+json"}
    req = urllib.request.Request(endpoint, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
        return body if is_construct else json.loads(body)


def count_triples():
    res = sparql_query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
    return int(res["results"]["bindings"][0]["c"]["value"])


def start_server(storage_dir):
    """Start an empty Tentris container with a writable datastore; wait until ready."""
    stop_tentris()
    os.makedirs(storage_dir, exist_ok=True)
    rc, _, stderr = docker_run([
        "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{TENTRIS_PORT}:{TENTRIS_PORT}",
        "-v", f"{os.path.abspath(storage_dir)}:/data",
        TENTRIS_IMAGE,
    ])
    if rc != 0:
        print(f"    Container start failed: {stderr}")
        return False
    # Wait for the SPARQL endpoint to answer (empty store returns count 0)
    for attempt in range(120):
        time.sleep(1)
        rc2, out2, _ = docker_run(["inspect", "--format", "{{.State.Running}}", CONTAINER_NAME], timeout=5)
        if rc2 != 0 or "false" in out2.lower():
            _, logs, _ = docker_run(["logs", "--tail", "20", CONTAINER_NAME], timeout=5)
            print(f"    Container exited unexpectedly. Logs:\n{logs}")
            return False
        try:
            count_triples()
            print(f"    Server ready (took {attempt + 1}s)")
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, OSError, KeyError, ValueError):
            if attempt % 15 == 14:
                print(f"    Waiting for server... ({attempt + 1}s)")
    print("    Server did not become ready within 120s")
    return False


def gsp_load(nt_path):
    """Load an N-Triples file into the default graph via the SPARQL Graph Store Protocol."""
    with open(nt_path, "rb") as f:
        body = f.read()
    url = f"http://localhost:{TENTRIS_PORT}/graph-store?default"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/n-triples"})
    with urllib.request.urlopen(req, timeout=LOAD_TIMEOUT) as resp:
        return resp.status


def start_and_load(scale, timeout):
    """Start an empty server, then time a Graph Store Protocol upload of {scale}.nt."""
    storage_dir = os.path.join(STORAGE_BASE, scale)
    if os.path.exists(storage_dir):
        shutil.rmtree(storage_dir, ignore_errors=True)
    if not start_server(storage_dir):
        return None

    nt_path = os.path.join(DATA_DIR, f"{scale}.nt")
    expected = EXPECTED_TRIPLES.get(scale, 0)
    t0 = time.perf_counter()
    try:
        status = gsp_load(nt_path)
    except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, OSError) as e:
        print(f"    Graph Store upload failed: {e}")
        return None
    elapsed = time.perf_counter() - t0

    # Verify the load landed
    try:
        n = count_triples()
    except Exception as e:
        print(f"    Count check failed after load: {e}")
        return None
    if expected and n < expected * 0.9:
        print(f"    Load incomplete: {n} triples (expected ~{expected}), HTTP {status}")
        return None
    print(f"    Loaded {n} triples via Graph Store Protocol in {elapsed:.1f}s")
    return elapsed


def bench_scale(scale):
    print(f"\n{'='*60}")
    print(f"TentrisDB (Docker, BETA, emulated on arm64) — {scale} dataset")
    print(f"{'='*60}")

    MEM.reset()
    load_timeout = LOAD_TIMEOUT if scale == "xlarge" else TIMEOUT

    t_load = start_and_load(scale, load_timeout)
    if t_load is not None:
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": "read_ntriples", "seconds": t_load, "peak_mb": None})
    else:
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": "read_ntriples", "seconds": "TIMEOUT", "peak_mb": None})
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": "read_turtle", "seconds": "N/A", "peak_mb": None})
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": "write_turtle", "seconds": "N/A", "peak_mb": None})
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": "write_ntriples", "seconds": "N/A", "peak_mb": None})
        return

    # Server engine: Turtle read + writes are N/A
    for op in ("read_turtle", "write_turtle", "write_ntriples"):
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": op, "seconds": "N/A", "peak_mb": None})

    print(f"\n  SPARQL queries ({scale}):")
    for qname in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]:
        if qname in UPDATE_QUERIES:
            print(f"    {qname}: N/A (SPARQL Update not benchmarked for Tentris)")
            RESULTS.append({"framework": "tentris", "scale": scale, "operation": f"query_{qname}", "seconds": "N/A", "peak_mb": None})
            RESULTS.append({"framework": "tentris", "scale": scale, "operation": f"query_{qname}_cold", "seconds": "N/A", "peak_mb": None})
            continue
        q = load_query(qname)
        _, t_cold = timed(f"  {qname} (warmup)", lambda: sparql_query(q), warmup=True)
        if t_cold is None:
            RESULTS.append({"framework": "tentris", "scale": scale, "operation": f"query_{qname}", "seconds": "TIMEOUT", "peak_mb": None})
            RESULTS.append({"framework": "tentris", "scale": scale, "operation": f"query_{qname}_cold", "seconds": "TIMEOUT", "peak_mb": None})
            continue
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": f"query_{qname}_cold", "seconds": t_cold, "peak_mb": None})
        times = []
        for _ in range(3):
            _, t = timed(f"  {qname}", lambda: sparql_query(q), warmup=True)
            if t is not None:
                times.append(t)
        best = min(times) if times else "TIMEOUT"
        if times:
            print(f"    {qname}: {best:.4f}s (best of 3)")
        RESULTS.append({"framework": "tentris", "scale": scale, "operation": f"query_{qname}", "seconds": best, "peak_mb": None})

    RESULTS.append({"framework": "tentris", "scale": scale, "operation": "peak_memory", "seconds": None, "peak_mb": MEM.peak_mb})
    stop_tentris()


def save_results():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "results_tentris.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"  Results saved ({len(RESULTS)} entries)")


if __name__ == "__main__":
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=60, check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Docker is not available. Please install and start Docker.")
        sys.exit(1)

    rc, stdout, _ = docker_run(["images", "-q", TENTRIS_IMAGE])
    if not stdout.strip():
        print(f"Pulling Tentris image ({TENTRIS_IMAGE})... (may run under emulation on arm64)")
        docker_run(["pull", TENTRIS_IMAGE], timeout=900)

    print("TentrisDB benchmark starting (Docker, BETA)...")
    MEM.start()

    for scale in ["medium", "large", "xlarge"]:
        if not os.path.exists(os.path.join(DATA_DIR, f"{scale}.nt")):
            print(f"\n  Skipping {scale} — data not found")
            continue
        try:
            bench_scale(scale)
        except Exception as e:
            print(f"\n  ERROR on {scale}: {e}")
        finally:
            save_results()
            gc.collect()

    stop_tentris()
    shutil.rmtree(STORAGE_BASE, ignore_errors=True)
    save_results()
    print("\nAll done — results saved to results/results_tentris.json")
