"""Convert raw engine dumps (q*.srj = SPARQL JSON, q*.nt / q*.ttl = graph, q*.err, q*.na) into canonical JSON.

Usage: ingest_raw.py ENGINE SCALE RAWDIR OUTDIR
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from norm import QUERIES, XSD, select_from_json, graph_from_text, save, save_error, save_na

engine, scale, rawdir, outdir = sys.argv[1:5]
for q in QUERIES:
    base = os.path.join(rawdir, q)
    try:
        if os.path.exists(base + ".err"):
            save_error(outdir, engine, scale, q, open(base + ".err").read())
        elif os.path.exists(base + ".na"):
            save_na(outdir, engine, scale, q, open(base + ".na").read())
        elif os.path.exists(base + ".cypher.json"):
            import json
            res = json.load(open(base + ".cypher.json"))[0]

            def t(v):
                if v is None:
                    return None
                if isinstance(v, bool):
                    return ["lit", str(v).lower(), XSD + "boolean"]
                if isinstance(v, int):
                    return ["lit", str(v), XSD + "integer"]
                if isinstance(v, float):
                    return ["lit", repr(v), XSD + "double"]
                return ["lit", str(v), XSD + "string"]
            save(outdir, engine, scale, q, {"type": "select", "vars": res["columns"],
                                            "rows": [[t(v) for v in d["row"]] for d in res["data"]]})
        elif os.path.exists(base + ".srj"):
            sel = select_from_json(open(base + ".srj").read())
            obj = {"type": "update", "after": sel} if q.startswith("q6") else sel
            save(outdir, engine, scale, q, obj)
        elif os.path.exists(base + ".nt"):
            save(outdir, engine, scale, q, graph_from_text(open(base + ".nt").read(), "ntriples"))
        elif os.path.exists(base + ".ttl"):
            save(outdir, engine, scale, q, graph_from_text(open(base + ".ttl").read(), "turtle"))
        else:
            save_error(outdir, engine, scale, q, "no output captured")
    except Exception as e:
        save_error(outdir, engine, scale, q, f"ingest failed: {e!r}")
    print(engine, scale, q, "ingested")
