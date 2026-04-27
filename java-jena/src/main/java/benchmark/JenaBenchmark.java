package benchmark;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.apache.jena.query.*;
import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.riot.Lang;
import org.apache.jena.riot.RDFDataMgr;

import java.io.*;
import java.nio.file.*;
import java.util.*;

public class JenaBenchmark {

    static List<Map<String, Object>> RESULTS = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        String dataDir = args.length > 0 ? args[0] : "../data";
        String queryDir = args.length > 1 ? args[1] : "../queries";

        // Warmup JVM
        System.out.println("JVM warmup...");
        Model warmup = ModelFactory.createDefaultModel();
        RDFDataMgr.read(warmup, dataDir + "/medium.ttl", Lang.TURTLE);
        warmup.close();
        System.gc();

        for (String scale : new String[]{"medium", "large", "xlarge"}) {
            System.out.println("\n" + "=".repeat(60));
            System.out.println("Jena -- " + scale + " dataset");
            System.out.println("=".repeat(60));

            benchIO(scale, dataDir, queryDir);
            System.gc();
            Thread.sleep(1000);
        }

        // Save results
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        String resultsDir = args.length > 2 ? args[2] : "../results";
        Files.writeString(Path.of(resultsDir + "/results_jena.json"), gson.toJson(RESULTS));
        System.out.println("\nResults saved to " + resultsDir + "/results_jena.json");
    }

    static void benchIO(String scale, String dataDir, String queryDir) throws Exception {
        String ttlPath = dataDir + "/" + scale + ".ttl";
        String ntPath = dataDir + "/" + scale + ".nt";

        // --- Read Turtle ---
        long t0 = System.nanoTime();
        Model model = ModelFactory.createDefaultModel();
        RDFDataMgr.read(model, ttlPath, Lang.TURTLE);
        double readTtl = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Read Turtle: %.4fs%n", readTtl);
        System.out.printf("  Triple count: %d%n", model.size());
        addResult("jena", scale, "read_turtle", readTtl);

        // --- Write Turtle ---
        String outTtl = dataDir + "/" + scale + "_jena_out.ttl";
        t0 = System.nanoTime();
        try (OutputStream os = new BufferedOutputStream(new FileOutputStream(outTtl))) {
            RDFDataMgr.write(os, model, Lang.TURTLE);
        }
        double writeTtl = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Write Turtle: %.4fs%n", writeTtl);
        addResult("jena", scale, "write_turtle", writeTtl);
        new File(outTtl).delete();

        // --- Write N-Triples ---
        String outNt = dataDir + "/" + scale + "_jena_out.nt";
        t0 = System.nanoTime();
        try (OutputStream os = new BufferedOutputStream(new FileOutputStream(outNt))) {
            RDFDataMgr.write(os, model, Lang.NTRIPLES);
        }
        double writeNt = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Write N-Triples: %.4fs%n", writeNt);
        addResult("jena", scale, "write_ntriples", writeNt);
        new File(outNt).delete();

        // --- Read N-Triples ---
        t0 = System.nanoTime();
        Model model2 = ModelFactory.createDefaultModel();
        RDFDataMgr.read(model2, ntPath, Lang.NTRIPLES);
        double readNt = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Read N-Triples: %.4fs%n", readNt);
        addResult("jena", scale, "read_ntriples", readNt);
        model2.close();

        // --- SPARQL Queries ---
        System.out.println("\n  SPARQL queries (" + scale + "):");
        for (String qname : new String[]{"q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"}) {
            String sparql = Files.readString(Path.of(queryDir + "/" + qname + ".rq"));

            // Warmup
            execQuery(model, sparql);

            // Best of 3
            double best = Double.MAX_VALUE;
            for (int i = 0; i < 3; i++) {
                t0 = System.nanoTime();
                execQuery(model, sparql);
                double elapsed = (System.nanoTime() - t0) / 1e9;
                best = Math.min(best, elapsed);
            }
            System.out.printf("    %s: %.4fs (best of 3)%n", qname, best);
            addResult("jena", scale, "query_" + qname, best);
        }

        model.close();
    }

    static void execQuery(Model model, String sparql) {
        try (QueryExecution qe = QueryExecutionFactory.create(sparql, model)) {
            ResultSet rs = qe.execSelect();
            while (rs.hasNext()) rs.next(); // consume results
        }
    }

    static void addResult(String framework, String scale, String operation, double seconds) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("framework", framework);
        r.put("scale", scale);
        r.put("operation", operation);
        r.put("seconds", Math.round(seconds * 10000.0) / 10000.0);
        RESULTS.add(r);
    }
}
