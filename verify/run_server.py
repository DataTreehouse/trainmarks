"""Capture query outputs from the Docker-based engines by reusing the bench scripts' own helpers
(same image, same container flags, same load path, same HTTP calls).

Usage: run_server.py ENGINE SCALE RAWDIR
ENGINE in qlever, virtuoso, graphdb, neo4j, tentris
Writes RAWDIR/q*.srj (SPARQL JSON), q5_construct.ttl, *.err, *.na
"""
import importlib.util
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from norm import ROOT as RB, QUERIES, Q6_CHECK, load_query, kind

engine, scale, rawdir = sys.argv[1:4]
os.makedirs(rawdir, exist_ok=True)
SCRIPTS = {"qlever": "qlever/bench_qlever.py", "virtuoso": "virtuoso/bench_virtuoso.py",
           "graphdb": "graphdb/bench_graphdb.py", "neo4j": "neo4j/bench_neo4j.py",
           "tentris": "tentris/bench_tentris.py"}
spec = importlib.util.spec_from_file_location("bench", os.path.join(RB, SCRIPTS[engine]))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
ttl = os.path.join(B.DATA_DIR, f"{scale}.ttl")
nt = os.path.join(B.DATA_DIR, f"{scale}.nt")


def write(name, ext, content):
    with open(os.path.join(rawdir, f"{name}.{ext}"), "w") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))


def http_error_body(e):
    try:
        return f"{e} :: {e.read().decode()[:1500]}"
    except Exception:
        return repr(e)


def run_sparql_engine(query_fn, update_fn=None):
    for q in QUERIES:
        text = load_query(q)
        k = kind(q)
        try:
            if k == "update":
                if update_fn is None:
                    write(q, "na", "SPARQL Update not run by the bench script for this engine")
                    continue
                resp = update_fn(text)
                write("q6_update_response", "txt", str(resp))
                write(q, "srj", query_fn(Q6_CHECK))
            elif k == "construct":
                write(q, "ttl", query_fn(text))
            else:
                write(q, "srj", query_fn(text))
            print(engine, scale, q, "ok")
        except Exception as e:
            msg = http_error_body(e) if hasattr(e, "read") else repr(e)
            write(q, "err", msg)
            print(engine, scale, q, "ERROR", msg[:300])


# ------------------------------------------------------------------ engines
if engine == "qlever":
    B.stop_qlever()
    _clean = B.clean_workdir

    def _clean_workdir():          # Linux bind mounts: let the non-root container user write (Docker Desktop on macOS doesn't care)
        _clean()
        os.chmod(B.WORK_DIR, 0o777)
    B.clean_workdir = _clean_workdir
    assert B.build_index(nt, input_format="ntriples"), "index build failed"   # bench queries the NT index
    assert B.start_server(), "server start failed"
    try:
        run_sparql_engine(B.sparql_query, None)
    finally:
        B.stop_qlever()

elif engine == "virtuoso":
    if os.environ.get("VIRT_IMAGE"):
        B.VIRTUOSO_IMAGE = os.environ["VIRT_IMAGE"]
    assert B.start_virtuoso(scale), "virtuoso start failed"
    try:
        B.bulk_load(ttl, "turtle")      # bench: TTL load, then CLEAR GRAPH + NT load, queries on NT data
        assert B.bulk_load(nt, "ntriples") is not False
        if os.environ.get("VIRT_GRANT"):   # extra experiment: give the anonymous SPARQL user update rights
            print("GRANT ->", B.isql('GRANT SPARQL_UPDATE TO "SPARQL";')[0], B.isql("DB.DBA.RDF_GRAPH_USER_PERMS_SET('http://benchmark.example/graph', 'SPARQL', 3);")[0])
        run_sparql_engine(B.sparql_query, B.sparql_update)
    finally:
        B.stop_virtuoso()

elif engine == "graphdb":
    assert B.start_graphdb(), "graphdb start failed"
    try:
        B.delete_repository()
        assert B.create_repository()
        B.server_import(os.path.basename(nt))
        run_sparql_engine(B.sparql_query, B.sparql_update)
    finally:
        B.stop_graphdb()

elif engine == "tentris":
    # The image binds [::]:9080 by default; this sandbox has no IPv6, so mount a config that binds 0.0.0.0.
    _orig = B.docker_run
    CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tentris-config")

    def _docker_run(args, timeout=B.TIMEOUT):
        if args and args[0] == "run" and B.TENTRIS_IMAGE in args:
            i = args.index(B.TENTRIS_IMAGE)
            args = args[:i] + ["-v", f"{CFG}:/config:ro"] + args[i:]
        return _orig(args, timeout)
    B.docker_run = _docker_run

    def tentris_update(text):     # extra, informational: the bench marks Q6 N/A for Tentris
        import urllib.parse, urllib.request
        req = urllib.request.Request(f"http://localhost:{B.TENTRIS_PORT}/update",
                                     data=urllib.parse.urlencode({"update": text}).encode())
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.read().decode()
    assert B.start_and_load(scale, B.LOAD_TIMEOUT) is not None, "tentris load failed"
    try:
        run_sparql_engine(B.sparql_query, tentris_update if os.environ.get("TENTRIS_Q6") else None)
    finally:
        B.stop_tentris()

elif engine == "neo4j":
    # Same container + n10s config as the bench, but smaller heap so it fits this sandbox (results unaffected).
    _orig = B.docker_run

    def _docker_run(args, timeout=B.TIMEOUT):
        args = [a.replace("heap_initial__size=4g", "heap_initial__size=2g")
                 .replace("heap_max__size=4g", "heap_max__size=2g")
                 .replace("pagecache_size=2g", "pagecache_size=512m") for a in args]
        args = ["4g" if a == "8g" else a for a in args]
        return _orig(args, timeout)
    B.docker_run = _docker_run
    if os.environ.get("NEO4J_FIXED"):
        from neo4j_fixed import FIXED
        B.CYPHER_QUERIES.update(FIXED)
    assert B.start_neo4j(), "neo4j start failed"
    try:
        assert B.init_n10s()
        assert B.clear_graph(scale)
        n = B.import_rdf(nt, "N-Triples", scale)
        print("imported", n)
        for q in QUERIES:
            if q not in B.CYPHER_QUERIES:
                write(q, "na", "no Cypher translation in bench script (recorded as N/A)")
                continue
            try:
                res = B.cypher(B.CYPHER_QUERIES[q], timeout=600)
                write(q, "cypher.json", res)
                print(engine, scale, q, "ok", len(res[0]["data"]))
            except Exception as e:
                write(q, "err", repr(e))
                print(engine, scale, q, "ERROR", repr(e)[:300])
        # Diagnostics: what did n10s make of :country ?
        diag = B.cypher("MATCH (c:Customer) RETURN keys(c) AS props, [(c)-[r]->() | type(r)] AS rels LIMIT 1")
        write("neo4j_customer_shape", "json", diag)
        diag2 = B.cypher("MATCH (n) RETURN count(n) AS nodes")
        diag3 = B.cypher("MATCH ()-[r]->() RETURN count(r) AS rels")
        write("neo4j_counts", "json", {"nodes": diag2, "rels": diag3})
    finally:
        B.stop_neo4j()
