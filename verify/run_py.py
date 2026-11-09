"""Capture query outputs for the Python engines: maplib, maplib_disk, oxigraph, oxigraph_disk, rudof, rdflib.

Usage: run_py.py ENGINE SCALE OUTDIR
Loads {scale}.ttl exactly as the bench script does, runs Q1-Q5, then Q6 once followed by Q6_CHECK.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from norm import (DATA, QUERIES, Q6_CHECK, load_query, kind, select_from_json, term_from_nt,
                  graph_from_text, save, save_error, save_na)

engine, scale, outdir = sys.argv[1:4]
ttl = os.path.join(DATA, f"{scale}.ttl")


# ---------------------------------------------------------------- engine adapters
class Maplib:
    def __init__(self, disk=False):
        from maplib import Model
        if disk:
            self.dir = tempfile.mkdtemp(prefix="maplibdisk")
            self.m = Model(storage_folder=self.dir)
        else:
            self.m = Model()
        self.m.read(ttl, parallel=True)

    def select(self, q):
        return select_from_json(self.m.query(q, return_json=True))

    def construct(self, q):
        return graph_from_text(self.m.query(q, return_json=True), "turtle")

    def update(self, q):
        self.m.update(q)


class Oxigraph:
    def __init__(self, disk=False):
        from pyoxigraph import Store, RdfFormat
        self.store = Store(tempfile.mkdtemp(prefix="oxidisk")) if disk else Store()
        with open(ttl, "rb") as f:
            self.store.load(f, format=RdfFormat.TURTLE)

    def select(self, q):
        from pyoxigraph import QueryResultsFormat
        res = self.store.query(q)
        return select_from_json(res.serialize(format=QueryResultsFormat.JSON).decode())

    def construct(self, q):
        from pyoxigraph import RdfFormat
        res = self.store.query(q)
        return graph_from_text(res.serialize(format=RdfFormat.N_TRIPLES).decode(), "ntriples")

    def update(self, q):
        self.store.update(q)


class Rudof:
    def __init__(self):
        import pyrudof
        self.r = pyrudof.Rudof()
        self.r.read_data(ttl, format=pyrudof.RDFFormat.Turtle)

    def _run(self, q):
        self.r.read_query(q)
        return self.r.run_query()

    def select(self, q):
        res = self._run(q)
        vars_ = [v.lstrip("?") for v in res.variables()] if callable(getattr(res, "variables", None)) else None
        rows_py = res.to_python()
        if vars_ is None:
            vars_ = [k.lstrip("?") for k in (rows_py[0].keys() if rows_py else [])]
        rows = [[term_from_nt(r.get("?" + v)) for v in vars_] for r in rows_py]
        return {"type": "select", "vars": vars_, "rows": rows}

    def construct(self, q):
        return graph_from_text(self._run(q).to_python(), "turtle")

    def update(self, q):
        raise NotImplementedError("rudof: SPARQL Update not supported (bench records N/A)")


class Rdflib:
    def __init__(self):
        import rdflib
        self.g = rdflib.Graph()
        self.g.parse(ttl, format="turtle")

    def select(self, q):
        return select_from_json(self.g.query(q).serialize(format="json").decode())

    def construct(self, q):
        return graph_from_text(self.g.query(q).serialize(format="nt").decode(), "ntriples")

    def update(self, q):
        self.g.update(q)


ADAPTERS = {
    "maplib": lambda: Maplib(),
    "maplib_disk": lambda: Maplib(disk=True),
    "oxigraph": lambda: Oxigraph(),
    "oxigraph_disk": lambda: Oxigraph(disk=True),
    "rudof": lambda: Rudof(),
    "rdflib": lambda: Rdflib(),
}

# ---------------------------------------------------------------- run
try:
    eng = ADAPTERS[engine]()
except Exception as e:
    for q in QUERIES:
        save_error(outdir, engine, scale, q, f"load failed: {e}")
    print(f"{engine}/{scale}: load failed: {e}")
    sys.exit(0)

for qname in QUERIES:
    q = load_query(qname)
    k = kind(qname)
    try:
        if k == "select":
            save(outdir, engine, scale, qname, eng.select(q))
        elif k == "construct":
            save(outdir, engine, scale, qname, eng.construct(q))
        else:
            if engine == "rudof":
                save_na(outdir, engine, scale, qname, "SPARQL Update not supported")
                continue
            eng.update(q)
            after = eng.select(Q6_CHECK)
            save(outdir, engine, scale, qname, {"type": "update", "after": after})
        print(f"{engine}/{scale}/{qname}: ok")
    except Exception as e:
        save_error(outdir, engine, scale, qname, repr(e))
        print(f"{engine}/{scale}/{qname}: ERROR {e!r}")
