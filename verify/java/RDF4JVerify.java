package benchmark;

import org.eclipse.rdf4j.model.BNode;
import org.eclipse.rdf4j.model.IRI;
import org.eclipse.rdf4j.model.Literal;
import org.eclipse.rdf4j.model.Value;
import org.eclipse.rdf4j.query.*;
import org.eclipse.rdf4j.repository.Repository;
import org.eclipse.rdf4j.repository.RepositoryConnection;
import org.eclipse.rdf4j.repository.sail.SailRepository;
import org.eclipse.rdf4j.rio.RDFFormat;
import org.eclipse.rdf4j.rio.Rio;
import org.eclipse.rdf4j.sail.memory.MemoryStore;
import com.google.gson.Gson;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/**
 * Load {scale}.ttl into a MemoryStore (as RDF4JBenchmark does for queries), run each query once, dump raw outputs.
 * Compiles against the existing shaded target/rdf4j-benchmark-1.0-SNAPSHOT.jar (no extra dependencies:
 * SPARQL JSON is written by hand with the bundled Gson).
 * args: ttl queriesDir outDir q6_check.rq
 */
public class RDF4JVerify {
    public static void main(String[] args) throws Exception {
        String ttl = args[0], qdir = args[1], out = args[2], check = args[3];
        Files.createDirectories(Path.of(out));
        Repository repo = new SailRepository(new MemoryStore());
        try (RepositoryConnection conn = repo.getConnection()) {
            conn.add(new FileInputStream(ttl), "", RDFFormat.TURTLE);
            String[] qs = {"q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"};
            for (String q : qs) {
                String sparql = Files.readString(Path.of(qdir, q + ".rq"));
                try {
                    if (q.startsWith("q6")) {
                        conn.prepareUpdate(QueryLanguage.SPARQL, sparql).execute();
                        select(conn, Files.readString(Path.of(check)), out + "/" + q + ".srj");
                    } else if (q.startsWith("q5")) {
                        try (OutputStream os = new FileOutputStream(out + "/" + q + ".nt")) {
                            conn.prepareGraphQuery(QueryLanguage.SPARQL, sparql).evaluate(Rio.createWriter(RDFFormat.NTRIPLES, os));
                        }
                    } else {
                        select(conn, sparql, out + "/" + q + ".srj");
                    }
                    System.out.println("rdf4j " + q + " ok");
                } catch (Exception e) {
                    Files.writeString(Path.of(out, q + ".err"), e.toString());
                    System.out.println("rdf4j " + q + " ERROR " + e);
                }
            }
        }
        repo.shutDown();
    }

    static Map<String, String> term(Value v) {
        Map<String, String> m = new LinkedHashMap<>();
        if (v instanceof IRI) { m.put("type", "uri"); m.put("value", v.stringValue()); }
        else if (v instanceof BNode) { m.put("type", "bnode"); m.put("value", ((BNode) v).getID()); }
        else {
            Literal l = (Literal) v;
            m.put("type", "literal"); m.put("value", l.getLabel());
            if (l.getLanguage().isPresent()) m.put("xml:lang", l.getLanguage().get());
            else m.put("datatype", l.getDatatype().stringValue());
        }
        return m;
    }

    static void select(RepositoryConnection c, String sparql, String path) throws Exception {
        try (TupleQueryResult res = c.prepareTupleQuery(QueryLanguage.SPARQL, sparql).evaluate()) {
            List<String> vars = res.getBindingNames();
            List<Map<String, Object>> rows = new ArrayList<>();
            while (res.hasNext()) {
                BindingSet bs = res.next();
                Map<String, Object> row = new LinkedHashMap<>();
                for (String v : vars) if (bs.getValue(v) != null) row.put(v, term(bs.getValue(v)));
                rows.add(row);
            }
            Map<String, Object> doc = Map.of("head", Map.of("vars", vars), "results", Map.of("bindings", rows));
            Files.writeString(Path.of(path), new Gson().toJson(doc));
        }
    }
}
