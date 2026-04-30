"""
Benchmark: Neo4j + neosemantics (n10s) — RDF import and Cypher queries via Docker.
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation (10 minutes for xlarge loading).

Neo4j is a native graph database using the labeled property graph model.
The neosemantics (n10s) plugin enables RDF import/export, mapping triples
to Neo4j's property graph.

I/O mapping:
  - read_turtle   → n10s RDF import of Turtle file
  - read_ntriples → n10s RDF import of N-Triples file
  - write_turtle / write_ntriples → N/A (using read + query only)

SPARQL queries are translated to equivalent Cypher queries since Neo4j's
native query language is Cypher, not SPARQL.

Prerequisites:
  - Docker installed and running
"""

import time
import json
import os
import gc
import signal
import subprocess
import urllib.request
import urllib.error

QUERIES_DIR = os.path.join(os.path.dirname(__file__), "..", "queries")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
RESULTS = []
TIMEOUT = 600  # 10 minutes default
LOAD_TIMEOUT = 600  # 10 minutes for large imports

NEO4J_IMAGE = "neo4j:5.26-community"
NEO4J_HTTP_PORT = 7474
NEO4J_BOLT_PORT = 7687
CONTAINER_NAME = "neo4j-bench"

# n10s plugin — version must match Neo4j major.minor
N10S_VERSION = "5.26.0"
N10S_JAR_URL = f"https://github.com/neo4j-labs/neosemantics/releases/download/{N10S_VERSION}/neosemantics-{N10S_VERSION}.jar"
N10S_JAR_NAME = f"neosemantics-{N10S_VERSION}.jar"

# Expected triple counts per scale (for validation)
EXPECTED_TRIPLES = {
    "medium": 98_000,
    "large": 1_001_000,
    "xlarge": 9_995_000,
}

# Cypher equivalents of the SPARQL benchmark queries.
# n10s maps RDF predicates to Neo4j properties/relationships.
# With handleVocabUris:"IGNORE", the local name is used directly.
# rdfs:label → name property (n10s default mapping), rdf:type → Neo4j labels
CYPHER_QUERIES = {
    "q1_count": """
        MATCH (n)
        RETURN count(n) AS count
    """,
    "q2_customer_orders": """
        MATCH (order)-[:placedBy]->(customer)
        WHERE order.totalAmount IS NOT NULL
          AND customer.label IS NOT NULL
        RETURN customer.label AS customer_name,
               count(order) AS order_count,
               sum(order.totalAmount) AS total_spend
        ORDER BY total_spend DESC
        LIMIT 20
    """,
    "q3_join_3_entities": """
        MATCH (order)-[:placedBy]->(customer),
              (order)-[:contains]->(product)
        WHERE customer.country = 'Norway'
          AND order.totalAmount IS NOT NULL
          AND order.orderStatus IS NOT NULL
          AND customer.label IS NOT NULL
          AND product.label IS NOT NULL
        RETURN customer.label AS customer_name,
               product.label AS product_name,
               order.totalAmount AS amount,
               order.orderStatus AS status
        ORDER BY amount DESC
        LIMIT 50
    """,
    "q4_optional_aggregation": """
        MATCH (customer:Customer)
        WHERE customer.country IS NOT NULL
          AND customer.segment IS NOT NULL
        OPTIONAL MATCH (order)-[:placedBy]->(customer)
        WHERE order.totalAmount IS NOT NULL
        RETURN customer.country AS country,
               customer.segment AS segment,
               count(DISTINCT customer) AS customers,
               count(DISTINCT order) AS orders,
               sum(order.totalAmount) AS revenue
        ORDER BY revenue DESC
    """,
}


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
    except Exception as e:
        signal.alarm(0)
        print(f"  {label}: ERROR — {e}")
        return None, None


def docker_run(args, timeout=TIMEOUT):
    """Run a Docker command with timeout."""
    cmd = ["docker"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def record(operation, scale, seconds):
    RESULTS.append({
        "framework": "neo4j",
        "scale": scale,
        "operation": operation,
        "seconds": seconds if seconds is not None else "TIMEOUT",
    })


def save_results():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "results_neo4j.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"  Results saved ({len(RESULTS)} entries)")


def stop_neo4j():
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=30)
    time.sleep(1)


def start_neo4j():
    """Start a fresh Neo4j container with n10s plugin and data mounted."""
    stop_neo4j()

    # Download n10s plugin JAR if not already cached
    plugins_dir = os.path.join(os.path.dirname(__file__), "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    jar_path = os.path.join(plugins_dir, N10S_JAR_NAME)

    if not os.path.exists(jar_path):
        print(f"    Downloading n10s plugin v{N10S_VERSION}...")
        try:
            urllib.request.urlretrieve(N10S_JAR_URL, jar_path)
            print(f"    Downloaded to {jar_path}")
        except Exception as e:
            print(f"    Failed to download n10s: {e}")
            return False

    # Start Neo4j with:
    # - n10s plugin mounted
    # - data mounted at /import for n10s file:// access
    # - auth disabled for benchmarking
    # - generous memory settings
    rc, stdout, stderr = docker_run([
        "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{NEO4J_HTTP_PORT}:{NEO4J_HTTP_PORT}",
        "-p", f"{NEO4J_BOLT_PORT}:{NEO4J_BOLT_PORT}",
        "-v", f"{os.path.abspath(plugins_dir)}:/var/lib/neo4j/plugins",
        "-v", f"{os.path.abspath(DATA_DIR)}:/import",
        "-e", "NEO4J_AUTH=none",
        "-e", "NEO4J_PLUGINS=[]",
        "-e", "NEO4J_server_memory_heap_initial__size=4g",
        "-e", "NEO4J_server_memory_heap_max__size=4g",
        "-e", "NEO4J_server_memory_pagecache_size=2g",
        "-e", "NEO4J_dbms_security_procedures_unrestricted=n10s.*",
        "-e", "NEO4J_dbms_security_procedures_allowlist=n10s.*",
        "-m", "8g",
        NEO4J_IMAGE,
    ])

    if rc != 0:
        print(f"    Container start failed: {stderr}")
        return False

    print(f"    Container started, waiting for Neo4j to be ready...")

    # Wait for Neo4j to be ready
    for attempt in range(120):
        time.sleep(1)

        # Check container is still running
        rc2, out2, _ = docker_run(["inspect", "--format", "{{.State.Running}}", CONTAINER_NAME], timeout=5)
        if rc2 != 0 or "false" in out2.lower():
            _, logs, _ = docker_run(["logs", "--tail", "30", CONTAINER_NAME], timeout=5)
            print(f"    Container exited unexpectedly. Logs:\n{logs}")
            return False

        try:
            req = urllib.request.Request(
                f"http://localhost:{NEO4J_HTTP_PORT}/db/neo4j/tx/commit",
                data=json.dumps({"statements": [{"statement": "RETURN 1"}]}).encode(),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                print(f"    Neo4j ready (took {attempt + 1}s)")
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, OSError):
            if attempt % 15 == 14:
                print(f"    Still waiting... ({attempt + 1}s)")

    print("    Neo4j did not become ready within 120 seconds")
    return False


def cypher(statement, timeout=30):
    """Execute a Cypher statement via the HTTP transactional API and return the result."""
    payload = json.dumps({"statements": [{"statement": statement}]})
    req = urllib.request.Request(
        f"http://localhost:{NEO4J_HTTP_PORT}/db/neo4j/tx/commit",
        data=payload.encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    body = json.loads(resp.read().decode())

    if body.get("errors"):
        raise RuntimeError(f"Cypher error: {body['errors']}")

    return body["results"]


def init_n10s():
    """Initialize the n10s plugin: constraint + graphconfig."""
    print("    Initializing n10s...")

    # Create the required uniqueness constraint
    try:
        cypher("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE")
    except Exception as e:
        print(f"    Warning creating constraint: {e}")

    # Initialize graph config
    # handleVocabUris: IGNORE → use local names as property keys (e.g., "label" not "http://www.w3.org/2000/01/rdf-schema#label")
    # handleMultival: OVERWRITE → keep single values (faster, our data doesn't use multivalued props)
    try:
        cypher("CALL n10s.graphconfig.init({handleVocabUris: 'IGNORE', handleMultival: 'OVERWRITE', keepLangTag: false, keepCustomDataTypes: false})")
        print("    n10s initialized")
        return True
    except Exception as e:
        print(f"    n10s init failed: {e}")
        return False


def clear_graph(scale="medium"):
    """Reset the database for a fresh import.

    For small datasets, delete in-memory. For large/xlarge, restart the
    container entirely — deleting millions of nodes in one transaction
    exceeds Neo4j's memory budget.
    """
    try:
        if scale in ("large", "xlarge"):
            # Restart container for large datasets to avoid OOM on delete
            print("    Restarting Neo4j for clean import...")
            if not start_neo4j():
                return False
            return init_n10s()
        else:
            # In-memory delete is fine for medium
            cypher("MATCH (n) DETACH DELETE n", timeout=120)
            try:
                cypher("CALL n10s.graphconfig.drop()")
            except:
                pass
            time.sleep(1)
            return init_n10s()
    except Exception as e:
        print(f"    Clear failed: {e}")
        # Fall back to restart
        print("    Falling back to container restart...")
        if not start_neo4j():
            return False
        return init_n10s()


def import_rdf(filepath, fmt, scale, timeout=LOAD_TIMEOUT):
    """Import an RDF file using n10s and return the number of triples imported."""
    filename = os.path.basename(filepath)
    # n10s uses file:// URIs for local files (mounted at /import inside container)
    file_uri = f"file:///import/{filename}"

    result = cypher(
        f"CALL n10s.rdf.import.fetch('{file_uri}', '{fmt}')",
        timeout=timeout,
    )

    # n10s returns: terminationStatus, triplesLoaded, triplesParsed, namespaces, extraInfo, callParams
    if result and result[0].get("data"):
        row = result[0]["data"][0]["row"]
        columns = result[0]["columns"]
        data = dict(zip(columns, row))
        triples_loaded = data.get("triplesLoaded", 0)
        status = data.get("terminationStatus", "UNKNOWN")
        print(f"    Imported {triples_loaded} triples (status: {status})")
        return triples_loaded
    return 0


def print_schema():
    """Print the Neo4j schema created by n10s to help debug query property names."""
    try:
        # Node labels
        res = cypher("CALL db.labels() YIELD label RETURN collect(label) AS labels")
        labels = res[0]["data"][0]["row"][0] if res and res[0]["data"] else []
        print(f"    Labels: {labels}")

        # Property keys
        res = cypher("CALL db.propertyKeys() YIELD propertyKey RETURN collect(propertyKey) AS keys")
        keys = res[0]["data"][0]["row"][0] if res and res[0]["data"] else []
        print(f"    Properties: {keys}")

        # Relationship types
        res = cypher("CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS types")
        types = res[0]["data"][0]["row"][0] if res and res[0]["data"] else []
        print(f"    Relationships: {types}")

        # Sample a few nodes
        res = cypher("MATCH (n) RETURN labels(n) AS l, keys(n) AS k LIMIT 3")
        if res and res[0]["data"]:
            for row in res[0]["data"]:
                print(f"    Sample node: labels={row['row'][0]}, props={row['row'][1]}")
    except Exception as e:
        print(f"    Schema inspection failed: {e}")


def bench_io(scale):
    """Benchmark RDF import for a given scale."""
    print(f"\n{'=' * 60}")
    print(f"Neo4j + n10s — {scale} dataset")
    print(f"{'=' * 60}")

    ttl_path = os.path.join(DATA_DIR, f"{scale}.ttl")
    nt_path = os.path.join(DATA_DIR, f"{scale}.nt")

    if not os.path.exists(ttl_path):
        print(f"  Skipping {scale} — {ttl_path} not found")
        return False

    expected = EXPECTED_TRIPLES.get(scale, 0)
    min_expected = int(expected * 0.9)
    load_timeout = LOAD_TIMEOUT if scale == "xlarge" else TIMEOUT

    # --- Read Turtle (import) ---
    if not clear_graph(scale):
        record("read_turtle", scale, None)
        record("write_turtle", scale, None)
        record("read_ntriples", scale, None)
        record("write_ntriples", scale, None)
        return False

    def do_import_ttl():
        return import_rdf(ttl_path, "Turtle", scale, timeout=load_timeout)

    triples_ttl, t_ttl = timed("Read Turtle (n10s import)", do_import_ttl, timeout=load_timeout)

    if triples_ttl is not None and triples_ttl >= min_expected:
        record("read_turtle", scale, t_ttl)
        if scale == "medium":
            print("  Schema after n10s import:")
            print_schema()
    else:
        if triples_ttl is not None:
            print(f"  WARNING: Only {triples_ttl} triples (expected >= {min_expected}). FAILED.")
        record("read_turtle", scale, None)

    # Write ops are N/A for Neo4j
    record("write_turtle", scale, None)

    # --- Read N-Triples (import) ---
    if not clear_graph(scale):
        record("read_ntriples", scale, None)
        record("write_ntriples", scale, None)
        return False

    def do_import_nt():
        return import_rdf(nt_path, "N-Triples", scale, timeout=load_timeout)

    triples_nt, t_nt = timed("Read N-Triples (n10s import)", do_import_nt, timeout=load_timeout)

    valid_nt = triples_nt is not None and triples_nt >= min_expected
    if valid_nt:
        record("read_ntriples", scale, t_nt)
    else:
        if triples_nt is not None:
            print(f"  WARNING: Only {triples_nt} triples (expected >= {min_expected}). FAILED.")
        record("read_ntriples", scale, None)

    record("write_ntriples", scale, None)

    # --- Cypher Queries (on N-Triples data if available) ---
    if valid_nt:
        print(f"\n  Cypher queries ({scale}):")
        for qname, cypher_text in CYPHER_QUERIES.items():
            # Warmup
            try:
                cypher(cypher_text, timeout=60)
            except Exception as e:
                print(f"    {qname}: warmup failed — {e}")
                record(f"query_{qname}", scale, None)
                continue

            # Best of 3
            times = []
            for _ in range(3):
                def run_query(q=cypher_text):
                    return cypher(q, timeout=TIMEOUT)
                _, t = timed(f"  {qname}", run_query, warmup=True, timeout=TIMEOUT)
                if t is not None:
                    times.append(t)

            if times:
                best = min(times)
                print(f"    {qname}: {best:.4f}s (best of 3)")
                record(f"query_{qname}", scale, best)
            else:
                print(f"    {qname}: TIMEOUT")
                record(f"query_{qname}", scale, None)
    else:
        print(f"\n  Skipping queries ({scale}) — no valid data loaded")
        for qname in CYPHER_QUERIES:
            record(f"query_{qname}", scale, None)

    return True


if __name__ == "__main__":
    import sys

    # Check Docker
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=60, check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Docker is not available. Please install and start Docker.")
        sys.exit(1)

    # Pull Neo4j image if needed
    print("Pulling Neo4j image (if needed)...")
    rc, _, stderr = docker_run(["pull", NEO4J_IMAGE], timeout=300)
    if rc != 0:
        print(f"  Warning: pull returned {rc}: {stderr}")

    # Start Neo4j
    if not start_neo4j():
        print("Failed to start Neo4j")
        sys.exit(1)

    # Initialize n10s
    if not init_n10s():
        print("Failed to initialize n10s")
        stop_neo4j()
        sys.exit(1)

    # Run benchmarks
    try:
        for scale in ["medium", "large", "xlarge"]:
            try:
                bench_io(scale)
            except Exception as e:
                print(f"\n  ERROR on {scale}: {e}")
                print("  Saving partial results and continuing...")
            finally:
                save_results()
    finally:
        print("\nStopping Neo4j container...")
        stop_neo4j()

    print(f"\nAll done — results saved to {RESULTS_DIR}/results_neo4j.json")
