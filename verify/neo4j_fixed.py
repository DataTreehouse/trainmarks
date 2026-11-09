"""Proposed corrected Cypher translations — run against the same n10s import to check they match SPARQL."""
FIXED = {
    # one RDF triple = one non-uri property, one relationship, or one rdf:type label (n10s adds :Resource to every node)
    "q1_count": """
        MATCH (n:Resource)          // skip n10s's own _GraphConfig node
        WITH sum(size(keys(n)) - 1) + sum(size(labels(n)) - 1) AS props_and_types
        MATCH ()-[r]->()
        WITH props_and_types, count(r) AS rels
        RETURN props_and_types + rels AS count
    """,
    # :country / :segment point at IRIs, so n10s stores them as relationships, not properties
    "q3_join_3_entities": """
        MATCH (order)-[:placedBy]->(customer)-[:country]->(:Resource {uri: 'http://benchmark.example/Norway'}),
              (order)-[:contains]->(product)
        WHERE order.totalAmount IS NOT NULL
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
        MATCH (customer:Customer)-[:country]->(c), (customer)-[:segment]->(s)
        OPTIONAL MATCH (order)-[:placedBy]->(customer)
        WHERE order.totalAmount IS NOT NULL
        RETURN c.uri AS country,
               s.uri AS segment,
               count(DISTINCT customer) AS customers,
               count(DISTINCT order) AS orders,
               sum(order.totalAmount) AS revenue
        ORDER BY revenue DESC
    """,
}
