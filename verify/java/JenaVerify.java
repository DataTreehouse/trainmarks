package benchmark;

import org.apache.jena.query.*;
import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.riot.Lang;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.update.UpdateAction;
import org.apache.jena.update.UpdateFactory;
import java.io.*;
import java.nio.file.*;

/** Load {scale}.ttl into an in-memory Model (as JenaBenchmark does), run each query once, dump raw outputs. */
public class JenaVerify {
    public static void main(String[] args) throws Exception {
        String ttl = args[0], qdir = args[1], out = args[2];  // args[3] = q6_check.rq
        Files.createDirectories(Path.of(out));
        Model model = ModelFactory.createDefaultModel();
        RDFDataMgr.read(model, ttl, Lang.TURTLE);
        String[] qs = {"q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"};
        for (String q : qs) {
            String sparql = Files.readString(Path.of(qdir, q + ".rq"));
            try {
                if (q.startsWith("q6")) {
                    UpdateAction.execute(UpdateFactory.create(sparql), model);
                    select(model, Files.readString(Path.of(args[3])), out + "/" + q + ".srj");
                } else if (q.startsWith("q5")) {
                    try (QueryExecution qe = QueryExecutionFactory.create(QueryFactory.create(sparql), model);
                         OutputStream os = new FileOutputStream(out + "/" + q + ".nt")) {
                        RDFDataMgr.write(os, qe.execConstruct(), Lang.NTRIPLES);
                    }
                } else {
                    select(model, sparql, out + "/" + q + ".srj");
                }
                System.out.println("jena " + q + " ok");
            } catch (Exception e) {
                Files.writeString(Path.of(out, q + ".err"), e.toString());
                System.out.println("jena " + q + " ERROR " + e);
            }
        }
    }
    static void select(Model m, String sparql, String path) throws Exception {
        try (QueryExecution qe = QueryExecutionFactory.create(QueryFactory.create(sparql), m);
             OutputStream os = new FileOutputStream(path)) {
            ResultSetFormatter.outputAsJSON(os, qe.execSelect());
        }
    }
}
