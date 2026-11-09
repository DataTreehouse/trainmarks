"""Compare canonical outputs across engines.

Usage: compare.py OUTDIR [SCALE ...]   -> prints a report and writes OUTDIR/summary.json

Equality rules
  * IRIs and strings: exact.
  * Numeric literals (integer family, decimal, float, double): compared by value,
    relative tolerance 1e-9 (floating-point SUM order differs between engines).
  * Datatype differences on equal values (e.g. COUNT -> xsd:unsignedInt vs xsd:integer,
    double*decimal -> xsd:decimal vs xsd:double) are reported separately as "type" notes.
  * SELECT columns are matched by variable name, not position.
  * ORDER BY queries are compared in order; rows that swap places only inside a tie
    on the sort key are accepted.
  * CONSTRUCT results are compared as sets of triples.
"""
import json
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from norm import QUERIES, XSD

NUMERIC = {XSD + t for t in ["integer", "int", "long", "short", "byte", "unsignedInt", "unsignedLong",
                             "unsignedShort", "unsignedByte", "nonNegativeInteger", "positiveInteger",
                             "negativeInteger", "nonPositiveInteger", "decimal", "double", "float"]}
SORT_KEY = {"q2_customer_orders": "total_spend", "q3_join_3_entities": "amount",
            "q4_optional_aggregation": "revenue"}
REL_TOL = 1e-9


def vkey(t):
    """Value key of a term (ignores datatype for numerics)."""
    if t is None:
        return ("unbound",)
    if t[0] == "iri":
        return ("iri", t[1])
    if t[0] == "bnode":
        return ("bnode",)
    lex, dt = t[1], t[2]
    if dt in NUMERIC:
        try:
            return ("num", float(lex))
        except ValueError:
            return ("badnum", lex)
    if dt == XSD + "string":
        return ("str", lex)
    return ("lit", lex, dt)


def veq(a, b):
    if a[0] == "num" and b[0] == "num":
        x, y = a[1], b[1]
        return x == y or math.isclose(x, y, rel_tol=REL_TOL, abs_tol=1e-6)
    return a == b


def row_eq(r1, r2):
    return len(r1) == len(r2) and all(veq(a, b) for a, b in zip(r1, r2))


def round_key(row):
    """Hashable, tolerance-friendly key for multiset comparison."""
    return tuple((k[0], round(k[1], 4)) if k[0] == "num" else k for k in row)


def select_rows(obj):
    vars_ = obj["vars"]
    order = sorted(range(len(vars_)), key=lambda i: vars_[i])
    names = [vars_[i] for i in order]
    rows = [[vkey(r[i]) for i in order] for r in obj["rows"]]
    types = Counter()
    for r in obj["rows"]:
        for i in order:
            t = r[i]
            if t and t[0] == "lit":
                types[(vars_[i], t[2].replace(XSD, "xsd:"))] += 1
    return names, rows, set(types)


def compare_select(qname, a, b):
    """Return (verdict, detail). verdict in {"same", "same (tie order)", "DIFF"}."""
    na, ra, _ = a
    nb, rb, _ = b
    if na != nb:
        return "DIFF", f"different variables {na} vs {nb}"
    if len(ra) != len(rb):
        return "DIFF", f"{len(ra)} rows vs {len(rb)} rows"
    if all(row_eq(x, y) for x, y in zip(ra, rb)):
        return "same", ""
    if Counter(map(round_key, ra)) == Counter(map(round_key, rb)):
        if qname in SORT_KEY:
            ki = na.index(SORT_KEY[qname])
            ok = all(row_eq(x, y) or veq(x[ki], y[ki]) for x, y in zip(ra, rb))
            if ok:
                return "same (tie order)", "rows with equal sort key in different order"
            return "DIFF", "same rows, different ORDER BY order"
        return "same", "same rows, different order (no ORDER BY)"
    # LIMIT boundary with ties?
    if qname in SORT_KEY:
        ki = na.index(SORT_KEY[qname])
        last = ra[-1][ki] if ra else None
        diff_a = Counter(map(round_key, ra)) - Counter(map(round_key, rb))
        diff_b = Counter(map(round_key, rb)) - Counter(map(round_key, ra))
        if last and all(veq(dict(enumerate(k))[ki], last) for k in list(diff_a) + list(diff_b)):
            return "same (tie at LIMIT)", "different rows chosen among ties at the LIMIT cut-off"
    first = next(i for i, (x, y) in enumerate(zip(ra, rb)) if not row_eq(x, y))
    return "DIFF", f"first differing row #{first}: {ra[first]} vs {rb[first]}"


def triple_set(obj):
    out = set()
    for s, p, o in obj["triples"]:
        k = vkey(o)
        if k[0] == "num":
            k = ("num", round(k[1], 6))
        out.add((tuple(s), tuple(p), k))
    return out


def load(outdir, engine, scale, q):
    p = os.path.join(outdir, engine, scale, f"{q}.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p))


def prep(q, obj):
    t = obj["type"]
    if t == "select":
        return ("select", select_rows(obj))
    if t == "update":
        return ("select", select_rows(obj["after"]))
    if t == "construct":
        return ("construct", triple_set(obj),
                {(p[1].rsplit("/", 1)[-1], o[2].replace(XSD, "xsd:")) for s, p, o in obj["triples"] if o[0] == "lit"})
    return (t, obj.get("error") or obj.get("why"))


def equal(q, a, b):
    if a[0] != b[0]:
        return "DIFF", f"{a[0]} vs {b[0]}"
    if a[0] == "select":
        return compare_select(q, a[1], b[1])
    if a[0] == "construct":
        if a[1] == b[1]:
            return "same", ""
        return "DIFF", f"{len(a[1])} vs {len(b[1])} triples; {len(a[1]-b[1])} only-left, {len(b[1]-a[1])} only-right"
    return "DIFF", "n/a"


def main():
    outdir = sys.argv[1]
    engines = sorted(e for e in os.listdir(outdir) if os.path.isdir(os.path.join(outdir, e)))
    scales = sys.argv[2:] or ["medium", "large"]
    summary = {}
    for scale in scales:
        print(f"\n######## scale = {scale}")
        for q in QUERIES:
            res = {}
            for e in engines:
                obj = load(outdir, e, scale, q)
                if obj is not None:
                    res[e] = prep(q, obj)
            runnable = {e: r for e, r in res.items() if r[0] in ("select", "construct")}
            # consensus = engine that agrees with the most others
            agree = {e: [f for f in runnable if equal(q, runnable[e], runnable[f])[0].startswith("same")]
                     for e in runnable}
            ref = max(runnable, key=lambda e: (len(agree[e]), e == "oxigraph")) if runnable else None
            print(f"\n== {q}  (reference: {ref}, agrees with {len(agree.get(ref, []))}/{len(runnable)})")
            rows = {}
            for e in engines:
                if e not in res:
                    continue
                r = res[e]
                if r[0] in ("na", "error"):
                    verdict, detail = r[0].upper(), r[1]
                else:
                    verdict, detail = equal(q, runnable[ref], r)
                    if r[0] == "select":
                        ref_types, my_types = runnable[ref][1][2], r[1][2]
                        tdiff = {v: dt for v, dt in my_types} if my_types != ref_types else {}
                        if tdiff and verdict.startswith("same"):
                            reft = {v: dt for v, dt in ref_types}
                            notes = [f"{v}: {dt} (ref {reft.get(v)})" for v, dt in sorted(my_types)
                                     if reft.get(v) != dt]
                            if notes:
                                detail = (detail + "; " if detail else "") + "types: " + ", ".join(notes)
                    if r[0] == "construct" and r[2] != runnable[ref][2] and verdict.startswith("same"):
                        reft = dict(runnable[ref][2])
                        notes = [f"{p}: {dt} (ref {reft.get(p)})" for p, dt in sorted(r[2]) if reft.get(p) != dt]
                        detail = (detail + "; " if detail else "") + "object types: " + ", ".join(notes)
                    if r[0] == "select":
                        n = len(r[1][1])
                    else:
                        n = len(r[1])
                    detail = f"[{n} rows/triples] " + detail
                rows[e] = {"verdict": verdict, "detail": detail}
                print(f"   {e:14s} {verdict:20s} {detail[:220]}")
            summary.setdefault(scale, {})[q] = {"reference": ref, "engines": rows}
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
