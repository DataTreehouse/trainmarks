#!/usr/bin/env python3
"""
update_report.py — Automatically update index.html with the latest benchmark results.

Reads all results/results_*.json files and rewrites the DATA block in index.html.

Usage:
    python update_report.py
"""

import json
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
REPORT_PATH = SCRIPT_DIR / "index.html"

# Map JSON operation names → DATA keys
OP_MAP = {
    "read_turtle": "read_turtle",
    "write_turtle": "write_turtle",
    "read_ntriples": "read_ntriples",
    "write_ntriples": "write_ntriples",
    "query_q1_count": "q1",
    "query_q2_customer_orders": "q2",
    "query_q3_join_3_entities": "q3",
    "query_q4_optional_aggregation": "q4",
    "query_q5_construct": "q5",
    "query_q6_delete_insert": "q6",
    "query_q1_count_cold": "q1_cold",
    "query_q2_customer_orders_cold": "q2_cold",
    "query_q3_join_3_entities_cold": "q3_cold",
    "query_q4_optional_aggregation_cold": "q4_cold",
    "query_q5_construct_cold": "q5_cold",
    "query_q6_delete_insert_cold": "q6_cold",
}

# Frameworks to include (skip kolibrie)
FRAMEWORKS = [
    "maplib", "maplib_disk", "oxigraph", "oxigraph_disk", "rudof", "rdflib",
    "jena", "rdf4j", "qlever", "virtuoso", "graphdb",
    "dotnetrdf", "neo4j", "tentris",
]
MEM_OPS = ["read_turtle", "write_turtle", "read_ntriples", "write_ntriples", "q1", "q2", "q3", "q4", "q5", "q6"]

SCALES = ["medium", "large", "xlarge"]
OPS = ["read_turtle", "write_turtle", "read_ntriples", "write_ntriples", "q1", "q2", "q3", "q4", "q5", "q6", "q1_cold", "q2_cold", "q3_cold", "q4_cold", "q5_cold", "q6_cold"]


def load_results():
    """Load all result JSON files into a nested dict: {framework: {scale: {op: value}}}."""
    data = {}
    for path in sorted(RESULTS_DIR.glob("results_*.json")):
        with open(path) as f:
            entries = json.load(f)

        for entry in entries:
            fw = entry["framework"]
            if fw not in FRAMEWORKS:
                continue

            scale = entry["scale"]
            if entry["operation"] == "peak_memory":
                # Docker engines: one container-level peak per scale
                peak = entry.get("peak_mb")
                if peak is not None:
                    d = data.setdefault(fw, {}).setdefault(scale, {})
                    d["_scale_peak"] = round(float(peak), 1)
                    d["mem"] = max(d.get("mem") or 0, d["_scale_peak"])
                continue
            op = OP_MAP.get(entry["operation"])
            if op is None:
                continue

            val = entry["seconds"]
            if val in ("N/A", "TIMEOUT", "ERROR") or val is None:
                val = None
            else:
                try:
                    val = round(float(val), 5)
                except (ValueError, TypeError):
                    val = None

            data.setdefault(fw, {}).setdefault(scale, {})[op] = val
            if op in MEM_OPS and entry.get("peak_mb") is not None:
                try:
                    data[fw][scale]["memop_" + op] = round(float(entry["peak_mb"]), 1)
                except (ValueError, TypeError):
                    pass

            # Track peak memory per scale (max across all operations)
            peak = entry.get("peak_mb")
            if peak is not None:
                try:
                    peak = round(float(peak), 1)
                    cur = data[fw][scale].get("mem")
                    if cur is None or peak > cur:
                        data[fw][scale]["mem"] = peak
                except (ValueError, TypeError):
                    pass

    return data


def format_value(v):
    """Format a single value for JS."""
    if v is None:
        return "null"
    return str(v)


def build_data_block(data):
    """Build the JS DATA object string."""
    lines = ["const DATA = {"]

    for fw in FRAMEWORKS:
        if fw not in data:
            continue
        lines.append(f"  {fw}: {{")
        for scale in SCALES:
            if scale not in data.get(fw, {}):
                # Write all nulls if scale is missing
                vals = {op: None for op in OPS}
            else:
                vals = data[fw][scale]

            io_parts = [f"{op}: {format_value(vals.get(op))}" for op in OPS[:4]]
            q_parts = [f"{op}: {format_value(vals.get(op))}" for op in OPS[4:10]]
            cold_parts = [f"{op}: {format_value(vals.get(op))}" for op in OPS[10:]]
            mem_val = format_value(vals.get("mem"))
            lines.append(f"    {scale}: {{")
            lines.append(f"      {', '.join(io_parts)},")
            lines.append(f"      {', '.join(q_parts)},")
            lines.append(f"      {', '.join(cold_parts)},")
            lines.append(f"      mem: {mem_val}")
            lines.append(f"    }},")
        lines.append(f"  }},")

    lines.append("};")
    return "\n".join(lines)


def build_memops_block(data):
    """Build the JS MEMOPS object (peak MB per operation). Docker engines only report a
    per-scale container peak, which is broadcast to every operation of that scale."""
    lines = ["const MEMOPS = {"]
    for fw in FRAMEWORKS:
        if fw not in data:
            continue
        rows = []
        for scale in SCALES:
            vals = data[fw].get(scale)
            if not vals:
                continue
            fallback = vals.get("_scale_peak")
            parts = [f"{op}: {format_value(vals.get('memop_' + op, fallback))}" for op in MEM_OPS]
            if all(p.endswith("null") for p in parts):
                continue
            rows.append(f"    {scale}: {{ {', '.join(parts)} }},")
        if rows:
            lines.append(f"  {fw}: {{")
            lines.extend(rows)
            lines.append("  },")
    lines.append("};")
    return "\n".join(lines)


def update_report(data):
    """Replace the DATA block in index.html."""
    html = REPORT_PATH.read_text()

    # Match from 'const DATA = {' to the closing '};'
    pattern = r"const DATA = \{.*?\};\s*\n"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        raise ValueError("Could not find 'const DATA = { ... };' in index.html")

    new_block = build_data_block(data) + "\n"
    html = html[:match.start()] + new_block + html[match.end():]

    mem_match = re.search(r"const MEMOPS = \{.*?\n\};\s*\n", html, re.DOTALL)
    if mem_match:
        html = html[:mem_match.start()] + build_memops_block(data) + "\n" + html[mem_match.end():]
    else:
        print("  (no MEMOPS block found — per-operation memory not updated)")

    REPORT_PATH.write_text(html)
    return match.start(), match.end()


def main():
    result_files = list(RESULTS_DIR.glob("results_*.json"))
    print(f"Found {len(result_files)} result files in {RESULTS_DIR}/")
    for f in sorted(result_files):
        print(f"  {f.name}")

    data = load_results()
    print(f"\nLoaded data for {len(data)} frameworks: {', '.join(data.keys())}")

    for fw in FRAMEWORKS:
        if fw in data:
            scales = list(data[fw].keys())
            print(f"  {fw}: {', '.join(scales)}")

    start, end = update_report(data)
    print(f"\nUpdated DATA block in {REPORT_PATH.name} (chars {start}-{end})")
    print("Done!")


if __name__ == "__main__":
    main()
