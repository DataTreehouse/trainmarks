"""The bench runs maplib SELECTs with streaming=True; check that mode returns the same rows as the default mode."""
import sys
from maplib import Model
sys.path.insert(0, __import__('os').path.dirname(__file__))
from norm import DATA, load_query
scale = sys.argv[1]
m = Model(); m.read(f'{DATA}/{scale}.ttl', parallel=True)
for q in ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"]:
    t = load_query(q)
    a = m.query(t, streaming=True)
    b = m.query(t)
    cols = sorted(a.columns)
    same = a.select(cols).equals(b.select(cols))
    if not same:   # allow float noise
        import polars as pl
        same = all((a[c] - b[c]).abs().max() < 1e-6 if a[c].dtype in (pl.Float64, pl.Float32) else a[c].equals(b[c]) for c in cols)
    print(scale, q, "streaming==default:", same, a.shape)
