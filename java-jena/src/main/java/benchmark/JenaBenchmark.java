package benchmark;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.apache.jena.query.*;
import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.riot.Lang;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.update.UpdateAction;
import org.apache.jena.update.UpdateFactory;
import org.apache.jena.update.UpdateRequest;

import java.io.*;
import java.nio.file.*;
import java.util.*;

public class JenaBenchmark {

    static List<Map<String, Object>> RESULTS = new ArrayList<>();
    static MemSampler MEM = new MemSampler();

    public static void main(String[] args) throws Exception {
        String dataDir = args.length > 0 ? args[0] : "../data";
        String queryDir = args.length > 1 ? args[1] : "../queries";

        MEM.start();  // background heap-usage sampler

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
        for (String qname : new String[]{"q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"}) {
            String sparql = Files.readString(Path.of(queryDir + "/" + qname + ".rq"));
            boolean isUpdate = isUpdateQuery(sparql);

            // Warmup (also recorded as cold timing)
            t0 = System.nanoTime();
            if (isUpdate) {
                execUpdate(model, sparql);
            } else {
                execQuery(model, sparql);
            }
            double coldTime = (System.nanoTime() - t0) / 1e9;
            addResult("jena", scale, "query_" + qname + "_cold", coldTime);

            // Best of 3
            double best = Double.MAX_VALUE;
            for (int i = 0; i < 3; i++) {
                t0 = System.nanoTime();
                if (isUpdate) {
                    execUpdate(model, sparql);
                } else {
                    execQuery(model, sparql);
                }
                double elapsed = (System.nanoTime() - t0) / 1e9;
                best = Math.min(best, elapsed);
            }
            System.out.printf("    %s: %.4fs (best of 3), cold: %.4fs%n", qname, best, coldTime);
            addResult("jena", scale, "query_" + qname, best);
        }

        model.close();
    }

    static boolean isUpdateQuery(String sparql) {
        for (String line : sparql.split("\n")) {
            String trimmed = line.trim().toUpperCase();
            if (trimmed.startsWith("PREFIX") || trimmed.isEmpty()) continue;
            return trimmed.startsWith("DELETE") || trimmed.startsWith("INSERT");
        }
        return false;
    }

    static void execUpdate(Model model, String sparql) {
        UpdateRequest request = UpdateFactory.create(sparql);
        UpdateAction.execute(request, model);
    }

    static void execQuery(Model model, String sparql) {
        Query query = QueryFactory.create(sparql);
        try (QueryExecution qe = QueryExecutionFactory.create(query, model)) {
            if (query.isConstructType()) {
                Model result = qe.execConstruct();
                result.size(); // force materialization
                result.close();
            } else {
                ResultSet rs = qe.execSelect();
                while (rs.hasNext()) rs.next(); // consume results
            }
        }
    }

    static void addResult(String framework, String scale, String operation, double seconds) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("framework", framework);
        r.put("scale", scale);
        r.put("operation", operation);
        r.put("seconds", Math.round(seconds * 10000.0) / 10000.0);
        // Peak JVM heap used (MB) during this operation, i.e. since the previous
        // addResult call. NOTE: this is heap-used, not process RSS, so it is a
        // different basis than the psutil RSS numbers from the Python engines.
        r.put("peak_mb", MEM.snapshotResetMb());
        RESULTS.add(r);
    }

    /** Background thread tracking the peak JVM heap used since the last snapshot. */
    static class MemSampler {
        private volatile long peak = 0;
        private volatile boolean running = false;

        static long usedBytes() {
            Runtime rt = Runtime.getRuntime();
            return rt.totalMemory() - rt.freeMemory();
        }

        void start() {
            running = true;
            peak = usedBytes();
            Thread t = new Thread(() -> {
                while (running) {
                    long u = usedBytes();
                    if (u > peak) peak = u;
                    try { Thread.sleep(50); } catch (InterruptedException e) { break; }
                }
            });
            t.setDaemon(true);
            t.start();
        }

        /** Return peak-used-heap (MB) since last call, then reset to current usage. */
        double snapshotResetMb() {
            long p = Math.max(peak, usedBytes());
            peak = usedBytes();
            return Math.round(p / (1024.0 * 1024.0) * 10.0) / 10.0;
        }
    }
}
