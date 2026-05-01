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
}

# Frameworks to include (skip kolibrie)
FRAMEWORKS = [
    "maplib", "oxigraph", "rdflib", "jena", "rdf4j",
    "qlever", "virtuoso", "maplib_disk", "graphdb",
    "dotnetrdf", "neo4j",
]

SCALES = ["medium", "large", "xlarge"]
OPS = ["read_turtle", "write_turtle", "read_ntriples", "write_ntriples", "q1", "q2", "q3", "q4"]


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
            q_parts = [f"{op}: {format_value(vals.get(op))}" for op in OPS[4:]]
            lines.append(f"    {scale}: {{")
            lines.append(f"      {', '.join(io_parts)},")
            lines.append(f"      {', '.join(q_parts)}")
            lines.append(f"    }},")
        lines.append(f"  }},")

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
