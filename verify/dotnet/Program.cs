// Load {scale}.nt into a TripleStore (the bench queries the N-Triples store), run each query once, dump raw outputs.
using VDS.RDF;
using VDS.RDF.Parsing;
using VDS.RDF.Query;
using VDS.RDF.Update;
using VDS.RDF.Writing;

var nt = args[0]; var qdir = args[1]; var outDir = args[2];
Directory.CreateDirectory(outDir);
var store = new TripleStore();
var g = new Graph();
new NTriplesParser().Load(g, nt);
store.Add(g);
var processor = new LeviathanQueryProcessor(store);
var updater = new LeviathanUpdateProcessor(store);
var jsonWriter = new SparqlJsonWriter();
string[] qs = ["q1_count", "q2_customer_orders", "q3_join_3_entities", "q4_optional_aggregation", "q5_construct", "q6_delete_insert"];
foreach (var q in qs)
{
    var text = File.ReadAllText(Path.Combine(qdir, q + ".rq"));
    try
    {
        if (q.StartsWith("q6"))
        {
            updater.ProcessCommandSet(new SparqlUpdateParser().ParseFromString(text));
            var check = File.ReadAllText(args[3]);
            var rs = (SparqlResultSet)processor.ProcessQuery(new SparqlQueryParser().ParseFromString(check));
            jsonWriter.Save(rs, Path.Combine(outDir, q + ".srj"));
        }
        else if (q.StartsWith("q5"))
        {
            var res = (IGraph)processor.ProcessQuery(new SparqlQueryParser().ParseFromString(text));
            new NTriplesWriter().Save(res, Path.Combine(outDir, q + ".nt"));
        }
        else
        {
            var rs = (SparqlResultSet)processor.ProcessQuery(new SparqlQueryParser().ParseFromString(text));
            jsonWriter.Save(rs, Path.Combine(outDir, q + ".srj"));
        }
        Console.WriteLine($"dotnetrdf {q} ok");
    }
    catch (Exception e)
    {
        File.WriteAllText(Path.Combine(outDir, q + ".err"), e.ToString());
        Console.WriteLine($"dotnetrdf {q} ERROR {e.Message}");
    }
}
