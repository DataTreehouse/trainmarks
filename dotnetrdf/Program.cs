using System.Diagnostics;
using System.Text.Json;
using VDS.RDF;
using VDS.RDF.Parsing;
using VDS.RDF.Query;
using VDS.RDF.Writing;

const int TIMEOUT_MS = 300_000; // 5 minutes
const int QUERY_RUNS = 3;

var dataDir = "/data";
var queriesDir = "/queries";
var resultsDir = "/results";
var results = new List<Dictionary<string, object>>();

Directory.CreateDirectory(resultsDir);

string[] scales = ["medium", "large", "xlarge"];

foreach (var scale in scales)
{
    var ttlPath = Path.Combine(dataDir, $"{scale}.ttl");
    var ntPath = Path.Combine(dataDir, $"{scale}.nt");

    if (!File.Exists(ttlPath))
    {
        Console.WriteLine($"\n  Skipping {scale} — {ttlPath} not found");
        continue;
    }

    Console.WriteLine($"\n{"".PadLeft(60, '=')}");
    Console.WriteLine($"dotNetRDF — {scale} dataset");
    Console.WriteLine($"{"".PadLeft(60, '=')}");

    try
    {
        // --- Read Turtle ---
        TripleStore? store = null;
        var tReadTtl = TimedOp($"Read Turtle", () =>
        {
            store = new TripleStore();
            var g = new Graph();
            var parser = new TurtleParser();
            parser.Load(g, ttlPath);
            store.Add(g);
        });
        RecordResult("read_turtle", scale, tReadTtl);

        if (store != null)
        {
            Console.WriteLine($"  Turtle triple count: {store.Graphs.Sum(g => g.Triples.Count)}");
        }

        // --- Validate triple count ---
        int tripleCount = 0;
        bool validLoad = false;
        if (store != null)
        {
            tripleCount = store.Graphs.Sum(g => g.Triples.Count);
            // Expected: medium ~98K, large ~1M, xlarge ~10M
            var expectedMin = scale switch
            {
                "medium" => 80_000,
                "large" => 800_000,
                "xlarge" => 8_000_000,
                _ => 0
            };
            validLoad = tripleCount >= expectedMin;
            if (!validLoad)
            {
                Console.WriteLine($"  WARNING: Only {tripleCount} triples loaded (expected >= {expectedMin}). Marking as FAILED.");
            }
        }

        // --- Write Turtle ---
        if (store != null && validLoad)
        {
            var outTtl = Path.Combine("/tmp", $"{scale}_dotnetrdf_out.ttl");
            var tWriteTtl = TimedOp("Write Turtle", () =>
            {
                var writer = new CompressingTurtleWriter();
                foreach (var g in store.Graphs)
                {
                    writer.Save(g, outTtl);
                    break; // write the first (default) graph
                }
            });
            RecordResult("write_turtle", scale, tWriteTtl);
            if (File.Exists(outTtl)) File.Delete(outTtl);
        }
        else
        {
            RecordResult("write_turtle", scale, null);
        }

        // --- Write N-Triples ---
        if (store != null && validLoad)
        {
            var outNt = Path.Combine("/tmp", $"{scale}_dotnetrdf_out.nt");
            var tWriteNt = TimedOp("Write N-Triples", () =>
            {
                var writer = new NTriplesWriter();
                foreach (var g in store.Graphs)
                {
                    writer.Save(g, outNt);
                    break;
                }
            });
            RecordResult("write_ntriples", scale, tWriteNt);
            if (File.Exists(outNt)) File.Delete(outNt);
        }
        else
        {
            RecordResult("write_ntriples", scale, null);
        }

        // Free memory before reading N-Triples
        store = null;
        GC.Collect();
        GC.WaitForPendingFinalizers();

        // --- Read N-Triples ---
        TripleStore? storeNt = null;
        var tReadNt = TimedOp("Read N-Triples", () =>
        {
            storeNt = new TripleStore();
            var g = new Graph();
            var parser = new NTriplesParser();
            parser.Load(g, ntPath);
            storeNt.Add(g);
        });
        RecordResult("read_ntriples", scale, tReadNt);

        // --- Validate N-Triples load ---
        bool validNtLoad = false;
        if (storeNt != null)
        {
            var ntTripleCount = storeNt.Graphs.Sum(g => g.Triples.Count);
            Console.WriteLine($"  N-Triples triple count: {ntTripleCount}");
            var expectedMin = scale switch
            {
                "medium" => 80_000,
                "large" => 800_000,
                "xlarge" => 8_000_000,
                _ => 0
            };
            validNtLoad = ntTripleCount >= expectedMin;
            if (!validNtLoad)
            {
                Console.WriteLine($"  WARNING: Only {ntTripleCount} triples from N-Triples (expected >= {expectedMin}). Marking as FAILED.");
            }
        }

        // --- SPARQL Queries ---
        var queryStore = (storeNt != null && validNtLoad) ? storeNt : (validLoad ? store : null);
        if (queryStore != null)
        {
            Console.WriteLine($"\n  SPARQL queries ({scale}):");
            var processor = new LeviathanQueryProcessor(queryStore);

            string[] queryNames = ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"];
            foreach (var qname in queryNames)
            {
                var queryPath = Path.Combine(queriesDir, $"{qname}.rq");
                if (!File.Exists(queryPath))
                {
                    Console.WriteLine($"    {qname}: query file not found");
                    continue;
                }
                var queryText = File.ReadAllText(queryPath);
                var sparqlParser = new SparqlQueryParser();
                var query = sparqlParser.ParseFromString(queryText);

                // Warmup
                try
                {
                    processor.ProcessQuery(query);
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"    {qname}: warmup failed — {ex.Message}");
                    RecordResult($"query_{qname}", scale, null);
                    continue;
                }

                // Best of 3
                var times = new List<double>();
                for (int i = 0; i < QUERY_RUNS; i++)
                {
                    var t = TimedOp($"  {qname}", () =>
                    {
                        // Re-parse the query for each run (dotNetRDF modifies the query object)
                        var q = sparqlParser.ParseFromString(queryText);
                        processor.ProcessQuery(q);
                    }, silent: true);
                    if (t.HasValue) times.Add(t.Value);
                }

                if (times.Count > 0)
                {
                    var best = times.Min();
                    Console.WriteLine($"    {qname}: {best:F4}s (best of {QUERY_RUNS})");
                    RecordResult($"query_{qname}", scale, best);
                }
                else
                {
                    Console.WriteLine($"    {qname}: TIMEOUT");
                    RecordResult($"query_{qname}", scale, null);
                }
            }
        }
        else
        {
            Console.WriteLine($"\n  Skipping SPARQL queries ({scale}) — no valid data loaded");
            string[] queryNames = ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation"];
            foreach (var qname in queryNames)
            {
                RecordResult($"query_{qname}", scale, null);
            }
        }

        // Cleanup
        storeNt = null;
        store = null;
        GC.Collect();
        GC.WaitForPendingFinalizers();
    }
    catch (Exception ex)
    {
        Console.WriteLine($"\n  ERROR on {scale}: {ex.Message}");
        Console.WriteLine("  Saving partial results and continuing...");
    }
    finally
    {
        // Save results incrementally
        SaveResults();
    }
}

Console.WriteLine($"\nAll done — results saved to {resultsDir}/results_dotnetrdf.json");

// ── Helpers ──

double? TimedOp(string label, Action action, bool silent = false)
{
    GC.Collect();
    GC.WaitForPendingFinalizers();

    var sw = Stopwatch.StartNew();
    try
    {
        var task = Task.Run(action);
        if (!task.Wait(TimeSpan.FromMilliseconds(TIMEOUT_MS)))
        {
            if (!silent) Console.WriteLine($"  {label}: TIMEOUT (>{TIMEOUT_MS / 1000}s)");
            return null;
        }
        sw.Stop();
        var elapsed = sw.Elapsed.TotalSeconds;
        if (!silent) Console.WriteLine($"  {label}: {elapsed:F4}s");
        return elapsed;
    }
    catch (AggregateException ex)
    {
        sw.Stop();
        if (!silent) Console.WriteLine($"  {label}: ERROR — {ex.InnerException?.Message ?? ex.Message}");
        return null;
    }
    catch (Exception ex)
    {
        sw.Stop();
        if (!silent) Console.WriteLine($"  {label}: ERROR — {ex.Message}");
        return null;
    }
}

void RecordResult(string operation, string scale, double? seconds)
{
    var entry = new Dictionary<string, object>
    {
        ["framework"] = "dotnetrdf",
        ["scale"] = scale,
        ["operation"] = operation,
    };
    if (seconds.HasValue)
        entry["seconds"] = seconds.Value;
    else
        entry["seconds"] = "TIMEOUT";
    results.Add(entry);
}

void SaveResults()
{
    var json = JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true });
    File.WriteAllText(Path.Combine(resultsDir, "results_dotnetrdf.json"), json);
    Console.WriteLine($"  Results saved ({results.Count} entries)");
}
