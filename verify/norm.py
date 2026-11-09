"""Normalisation helpers: turn every engine's output into one canonical JSON shape.

Term encoding:
  ["iri", "<full iri>"]
  ["lit", "lexical", "datatype-iri"]   (plain strings get xsd:string, lang tags "@en")
  ["bnode", id]
  None                                  (unbound)
"""
import json
import os
import re
import tempfile

XSD = "http://www.w3.org/2001/XMLSchema#"
ROOT = os.environ.get("RB_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
QDIR = os.path.join(ROOT, "queries")
DATA = os.path.join(ROOT, "data")
QUERIES = ["q1_count", "q2_customer_orders", "q3_join_3_entities",
           "q4_optional_aggregation", "q5_construct", "q6_delete_insert"]

# After Q6 runs once on a freshly loaded store, every engine dumps the new price state with this.
Q6_CHECK = """PREFIX : <http://benchmark.example/>
SELECT ?product ?price WHERE { ?product :unitPrice ?price } ORDER BY ?product ?price"""


def load_query(name):
    with open(os.path.join(QDIR, f"{name}.rq")) as f:
        return f.read()


def kind(name):
    if name.startswith("q5"):
        return "construct"
    if name.startswith("q6"):
        return "update"
    return "select"


def term_from_json(b):
    if b is None:
        return None
    t = b["type"]
    if t == "uri":
        return ["iri", b["value"]]
    if t == "bnode":
        return ["bnode", b["value"]]
    if "xml:lang" in b:
        return ["lit", b["value"], "@" + b["xml:lang"].lower()]
    return ["lit", b["value"], b.get("datatype", XSD + "string")]


def select_from_json(js):
    if isinstance(js, str):
        js = json.loads(js)
    vars_ = js["head"]["vars"]
    rows = [[term_from_json(r.get(v)) for v in vars_] for r in js["results"]["bindings"]]
    return {"type": "select", "vars": vars_, "rows": rows}


_LIT = re.compile(r'^"((?:[^"\\]|\\.)*)"(?:\^\^<([^>]*)>|@([A-Za-z0-9-]+))?$', re.S)


def _unescape(s):
    return (s.replace('\\"', '"').replace("\\n", "\n").replace("\\r", "\r")
             .replace("\\t", "\t").replace("\\\\", "\\"))


def term_from_nt(tok):
    """Parse a single N-Triples-style term string."""
    if tok is None or tok == "":
        return None
    tok = tok.strip()
    if tok.startswith("<"):
        return ["iri", tok[1:-1]]
    if tok.startswith("_:"):
        return ["bnode", tok[2:]]
    m = _LIT.match(tok)
    if m:
        lex, dt, lang = m.groups()
        if lang:
            return ["lit", _unescape(lex), "@" + lang.lower()]
        return ["lit", _unescape(lex), dt or XSD + "string"]
    raise ValueError(f"cannot parse term {tok!r}")


def graph_from_text(text, fmt="turtle"):
    """Parse an RDF graph serialisation with maplib and return the triples as canonical terms."""
    from maplib import Model
    suffix = {"turtle": ".ttl", "ntriples": ".nt"}[fmt]
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
        f.write(text)
        path = f.name
    try:
        m = Model()
        if text.strip():
            m.read(path, format=fmt)
        js = m.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o }", return_json=True)
    finally:
        os.unlink(path)
    js = json.loads(js) if isinstance(js, str) else js
    # maplib's head.vars order is not the projection order, so pick s/p/o by name
    rows = [[term_from_json(b.get(v)) for v in ("s", "p", "o")] for b in js["results"]["bindings"]]
    return {"type": "construct", "triples": rows}


def save(outdir, engine, scale, qname, obj, extra=None):
    os.makedirs(os.path.join(outdir, engine, scale), exist_ok=True)
    if extra:
        obj = dict(obj, **extra)
    with open(os.path.join(outdir, engine, scale, f"{qname}.json"), "w") as f:
        json.dump(obj, f)


def save_error(outdir, engine, scale, qname, err):
    save(outdir, engine, scale, qname, {"type": "error", "error": str(err)[:2000]})


def save_na(outdir, engine, scale, qname, why):
    save(outdir, engine, scale, qname, {"type": "na", "why": why})
