package benchmark;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.eclipse.rdf4j.model.Model;
import org.eclipse.rdf4j.model.Statement;
import org.eclipse.rdf4j.query.BindingSet;
import org.eclipse.rdf4j.query.TupleQuery;
import org.eclipse.rdf4j.query.TupleQueryResult;
import org.eclipse.rdf4j.repository.Repository;
import org.eclipse.rdf4j.repository.RepositoryConnection;
import org.eclipse.rdf4j.repository.sail.SailRepository;
import org.eclipse.rdf4j.rio.RDFFormat;
import org.eclipse.rdf4j.rio.Rio;
import org.eclipse.rdf4j.sail.memory.MemoryStore;

import java.io.*;
import java.nio.file.*;
import java.util.*;

public class RDF4JBenchmark {

    static List<Map<String, Object>> RESULTS = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        String dataDir = args.length > 0 ? args[0] : "../data";
        String queryDir = args.length > 1 ? args[1] : "../queries";

        // Warmup JVM
        System.out.println("JVM warmup...");
        Repository warmupRepo = new SailRepository(new MemoryStore());
        try (RepositoryConnection conn = warmupRepo.getConnection()) {
            conn.add(new FileInputStream(dataDir + "/medium.ttl"), "", RDFFormat.TURTLE);
        }
        warmupRepo.shutDown();
        System.gc();

        for (String scale : new String[]{"medium", "large", "xlarge"}) {
            System.out.println("\n" + "=".repeat(60));
            System.out.println("RDF4J -- " + scale + " dataset");
            System.out.println("=".repeat(60));

            benchIO(scale, dataDir, queryDir);
            System.gc();
            Thread.sleep(1000);
        }

        // Save results
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        String resultsDir = args.length > 2 ? args[2] : "../results";
        Files.writeString(Path.of(resultsDir + "/results_rdf4j.json"), gson.toJson(RESULTS));
        System.out.println("\nResults saved to " + resultsDir + "/results_rdf4j.json");
    }

    static void benchIO(String scale, String dataDir, String queryDir) throws Exception {
        String ttlPath = dataDir + "/" + scale + ".ttl";
        String ntPath = dataDir + "/" + scale + ".nt";

        // --- Read Turtle ---
        long t0 = System.nanoTime();
        Repository repo = new SailRepository(new MemoryStore());
        RepositoryConnection conn = repo.getConnection();
        conn.add(new FileInputStream(ttlPath), "", RDFFormat.TURTLE);
        double readTtl = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Read Turtle: %.4fs%n", readTtl);
        System.out.printf("  Triple count: %d%n", conn.size());
        addResult("rdf4j", scale, "read_turtle", readTtl);

        // --- Write Turtle ---
        String outTtl = dataDir + "/" + scale + "_rdf4j_out.ttl";
        t0 = System.nanoTime();
        try (OutputStream os = new BufferedOutputStream(new FileOutputStream(outTtl))) {
            conn.export(Rio.createWriter(RDFFormat.TURTLE, os));
        }
        double writeTtl = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Write Turtle: %.4fs%n", writeTtl);
        addResult("rdf4j", scale, "write_turtle", writeTtl);
        new File(outTtl).delete();

        // --- Write N-Triples ---
        String outNt = dataDir + "/" + scale + "_rdf4j_out.nt";
        t0 = System.nanoTime();
        try (OutputStream os = new BufferedOutputStream(new FileOutputStream(outNt))) {
            conn.export(Rio.createWriter(RDFFormat.NTRIPLES, os));
        }
        double writeNt = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Write N-Triples: %.4fs%n", writeNt);
        addResult("rdf4j", scale, "write_ntriples", writeNt);
        new File(outNt).delete();

        conn.close();
        repo.shutDown();

        // --- Read N-Triples ---
        t0 = System.nanoTime();
        Repository repo2 = new SailRepository(new MemoryStore());
        RepositoryConnection conn2 = repo2.getConnection();
        conn2.add(new FileInputStream(ntPath), "", RDFFormat.NTRIPLES);
        double readNt = (System.nanoTime() - t0) / 1e9;
        System.out.printf("  Read N-Triples: %.4fs%n", readNt);
        addResult("rdf4j", scale, "read_ntriples", readNt);
        conn2.close();
        repo2.shutDown();

        // --- Reopen for queries ---
        Repository repoQ = new SailRepository(new MemoryStore());
        RepositoryConnection connQ = repoQ.getConnection();
        connQ.add(new FileInputStream(ttlPath), "", RDFFormat.TURTLE);

        // --- SPARQL Queries ---
        System.out.println("\n  SPARQL queries (" + scale + "):");
        for (String qname : new String[]{"q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"}) {
            String sparql = Files.readString(Path.of(queryDir + "/" + qname + ".rq"));

            // Warmup
            execQuery(connQ, sparql);

            // Best of 3
            double best = Double.MAX_VALUE;
            for (int i = 0; i < 3; i++) {
                t0 = System.nanoTime();
                execQuery(connQ, sparql);
                double elapsed = (System.nanoTime() - t0) / 1e9;
                best = Math.min(best, elapsed);
            }
            System.out.printf("    %s: %.4fs (best of 3)%n", qname, best);
            addResult("rdf4j", scale, "query_" + qname, best);
        }

        connQ.close();
        repoQ.shutDown();
    }

    static void execQuery(RepositoryConnection conn, String sparql) {
        TupleQuery query = conn.prepareTupleQuery(sparql);
        try (TupleQueryResult result = query.evaluate()) {
            while (result.hasNext()) result.next(); // consume results
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
