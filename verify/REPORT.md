# Trainmarks: do the engines return the same answers?

Checked on 26 October 2026, at the **medium** scale (98,000 triples) and the **large** scale (1,001,000 triples).

## Short answer

Thirteen engine setups run their queries the same way the bench scripts do. Eleven of them return the same results for every query they support, at both scales. Two do not:

| | Q1 count | Q2 top customers | Q3 3-way join | Q4 OPTIONAL agg | Q5 CONSTRUCT | Q6 update |
|---|---|---|---|---|---|---|
| maplib | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| oxigraph / oxigraph (disk) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| rudof | ✅ | ✅ | ✅ | ✅ | ✅ | N/A |
| rdflib | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Jena | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| RDF4J | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| dotNetRDF | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| QLever | ✅ | ✅ | ✅ | ✅ | ✅ | N/A |
| GraphDB | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tentris | ✅ | ✅ | ✅ | ✅ | ✅ | N/A (but it works now, see 5) |
| **Virtuoso** | ✅ | ✅ | ❌ **wrong rows** | ✅ | ✅ | ❌ **never runs** |
| **Neo4j + n10s** | ❌ 14,216 vs 98,000 | ✅ | ❌ **0 rows** | ❌ **0 rows** | N/A | N/A |

Size of each result: Q1 = 1 row, Q2 = 20, Q3 = 50, Q4 = 50. Q5 = 3,878 triples at medium and 43,091 at large. Q6 = 200 product prices at medium and 2,000 at large.

## What "the same" means here

- **Data:** I regenerated it with `generate_data.py`. The md5 checksums of `medium.ttl/.nt` and `large.ttl/.nt` match the files in `data/`.
- **Loading:** each engine loads the data the same way its bench script does: the same format (TTL or NT), the same API or container flags, and the same HTTP endpoint. The server engines are driven through the bench scripts' own helper functions.
- **Q1–Q5:** each runs once. **Q6** runs once on a freshly loaded store. Then `SELECT ?product ?price WHERE { ?product :unitPrice ?price }` dumps the new prices for comparison. (The bench itself runs Q6 four times in a row on the same store. That is fine for timing, but those results can't be compared.)
- **Comparison rules:**
  - IRIs and strings must match exactly.
  - Numbers are compared by value, with a relative tolerance of 1e-9, because floating-point SUMs differ in the last digits between engines.
  - In `ORDER BY` queries the order must match too. The only exception is rows that tie on the sort key; none did.
  - CONSTRUCT results are compared as sets of triples.
  - Differences in datatype alone are listed separately (section 4).
- **Self-test:** I deliberately broke the results five ways: changed one SUM by 0.01, swapped two ordered rows, dropped a row, dropped a triple, and changed one price. The comparator caught all five.

## Findings

### 1. Virtuoso 7.2.17 sorts stored numbers as text, so Q3 returns the wrong 50 rows

The query says `ORDER BY DESC(?amount)`. Virtuoso returns amounts starting `994.66, 992.29, 987.23…` instead of `4999.47, 4999.45…`. The same happens with the bench's own settings, with a default container, with TTL or NT loading, and with or without the full-text rule. Here is a minimal repro with three doubles (`verify/virtuoso_orderby_check.sh`):

```
7.2.14 (07.20.3240):  4999.47 994.66 50.1   ✅
7.2.17 (07.20.3243):  994.66 50.1 4999.47   ❌ (text order)
```

Q2 and Q4 are not affected. They sort on computed SUMs, and only stored literals are sorted wrongly. `MAX(?amount)` and `ORDER BY DESC(xsd:double(?amount))` are both correct. With `openlink/virtuoso-opensource-7:7.2.14`, Q1–Q5 all match the other engines (I checked this).

**Suggested fix:** pin the image to `7.2.14` and note it in the README. Rewriting Q3 for Virtuoso alone would make the comparison unfair. This is probably worth reporting to OpenLink.

### 2. Virtuoso Q6 never runs, which is why `results_virtuoso.json` has no Q6 rows

`sparql_update()` posts to the anonymous `/sparql` endpoint, and Virtuoso rejects the request:

```
SR186: No permission to execute procedure DB.DBA.SPARQL_MODIFY_BY_DICT_CONTENTS (user SPARQL)
```

The exception skips the Q6 records, and the outer `try` hides it. Granting update rights fixes this. I checked it: Virtuoso then reports "delete 200, insert 200", and the new prices match all the other engines. The fix is two lines in `start_virtuoso()`, after the limits are set:

```python
isql('GRANT SPARQL_UPDATE TO "SPARQL";', timeout=10)
isql("DB.DBA.RDF_GRAPH_USER_PERMS_SET('http://benchmark.example/graph', 'SPARQL', 3);", timeout=10)
```

### 3. Three of the four Neo4j Cypher translations don't ask the same question

n10s stores IRI-valued objects (`:country :Norway`, `:segment :SMB`) as **relationships**. The Cypher filters on them as if they were **properties**.

- **Q1** `MATCH (n) RETURN count(n)` counts nodes, not triples. It gives 14,216 at medium and 145,016 at large, against 98,000 and 1,001,000 triples.
- **Q3** `WHERE customer.country = 'Norway'` matches nothing, so it returns **0 rows**.
- **Q4** `WHERE customer.country IS NOT NULL AND customer.segment IS NOT NULL` also returns **0 rows**.

The published Neo4j Q1, Q3 and Q4 timings therefore measure a different query (Q1) or an empty result (Q3, Q4). Corrected translations are in `verify/neo4j_fixed.py`. They give results identical to SPARQL at both scales:

```cypher
// Q1: one triple = one non-uri property, one relationship, or one rdf:type label (skip n10s's _GraphConfig node)
MATCH (n:Resource)
WITH sum(size(keys(n)) - 1) + sum(size(labels(n)) - 1) AS props_and_types
MATCH ()-[r]->()
WITH props_and_types, count(r) AS rels
RETURN props_and_types + rels AS count

// Q3: filter Norway via the relationship
MATCH (order)-[:placedBy]->(customer)-[:country]->(:Resource {uri: 'http://benchmark.example/Norway'}),
      (order)-[:contains]->(product)
...  (rest unchanged)

// Q4: country and segment via relationships
MATCH (customer:Customer)-[:country]->(c), (customer)-[:segment]->(s)
OPTIONAL MATCH (order)-[:placedBy]->(customer)
WHERE order.totalAmount IS NOT NULL
RETURN c.uri AS country, s.uri AS segment,
       count(DISTINCT customer) AS customers, count(DISTINCT order) AS orders,
       sum(order.totalAmount) AS revenue
ORDER BY revenue DESC
```

The Neo4j Q2 translation was already correct.

### 4. Datatype-only differences (the values are equal)

None of these changes an answer, but some are spec deviations worth knowing about if someone asks:

- **maplib:** `COUNT` returns `xsd:unsignedInt`, where SPARQL says `xsd:integer`. Also, `head.vars` in the JSON output is not in SELECT order (cosmetic).
- **maplib and rdflib:** Q6 `xsd:double × 1.10` gives `xsd:decimal`. Under the XPath promotion rules the result should be `xsd:double`. Virtuoso does the same when the grants are added.
- **QLever:** `COUNT` returns `xsd:int`. Stored `xsd:double` values come back as `xsd:decimal`. Its Turtle output writes doubles as bare `4809.49`, which a parser reads as a decimal.
- **Virtuoso:** CONSTRUCT Turtle also writes doubles as bare decimals, for example `3648.5100000000002183`.

### 5. Smaller things I noticed

- **Neo4j plugins folder:** `neo4j/plugins/` contains **two** n10s jars, `neosemantics-5.26.0.jar` and `neosemantics-2025.06.1.jar`. The whole folder is mounted into Neo4j 5.26. I ran with 5.26.0 only. Removing the 2025.06.1 jar avoids a possible class clash.
- **Tentris:** the current `latest` image is 1.4.0. It has a working `/update` endpoint, and Q6 gave the correct prices (200 removed, 200 inserted). Q6 no longer needs to be N/A for Tentris. The image also binds `[::]:9080` by default, which fails on hosts without IPv6. It worked on your machine, but `verify/tentris-config/` has the workaround in case it's ever needed.
- **maplib streaming:** the bench runs maplib SELECTs with `streaming=True`. I checked that this mode returns exactly the same rows as the default mode (`maplib_streaming_check.py`).

## Not covered by this run

- **maplib (disk):** the public wheel raises "Contact Data Treehouse to try!" for `storage_folder`.
- **maplib 0.20.29:** this version isn't on PyPI, so I used 0.20.26.
- **xlarge:** the sandbox had 7 GB of RAM, so I couldn't run this scale.
- **Blazegraph, Kolibrie and Comunica:** they have results files but no scripts in the repo.

All of these can be run on your machine with the harness:

```bash
cd rdf-benchmark
bash verify/run_verify.sh medium                     # all engines
bash verify/run_verify.sh xlarge maplib jena qlever  # or a subset
```

`run_verify.sh` needs `uv`, Java 25 (for RDF4J, as in your pom) and Docker. It reuses the jars already built in `java-*/target/`.
