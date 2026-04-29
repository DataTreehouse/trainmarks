///
/// Benchmark: Kolibrie — I/O and SPARQL queries.
/// Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
/// Timeout: 5 minutes per operation.
///
/// Kolibrie is a Rust-based RDF query engine developed at KU Leuven's
/// Stream Intelligence Lab. It features dictionary-encoded storage,
/// a Volcano-style query optimizer (Streamertail), SIMD-accelerated
/// filtering, and streaming RDF support.
///
/// Build: cargo build --release
/// Run:   cargo run --release
///
use kolibrie::execute_query::execute_query;
use kolibrie::sparql_database::SparqlDatabase;
use serde::Serialize;
use std::fs;
use std::path::Path;
use std::time::Instant;

const TIMEOUT_SECS: u64 = 300; // 5 minutes

#[derive(Serialize)]
struct BenchResult {
    framework: String,
    scale: String,
    operation: String,
    seconds: serde_json::Value, // f64 or "TIMEOUT"
}

impl BenchResult {
    fn ok(scale: &str, operation: &str, seconds: f64) -> Self {
        BenchResult {
            framework: "kolibrie".to_string(),
            scale: scale.to_string(),
            operation: operation.to_string(),
            seconds: serde_json::json!(seconds),
        }
    }
    fn timeout(scale: &str, operation: &str) -> Self {
        BenchResult {
            framework: "kolibrie".to_string(),
            scale: scale.to_string(),
            operation: operation.to_string(),
            seconds: serde_json::json!("TIMEOUT"),
        }
    }
}

/// Time a closure, returning (result, elapsed_seconds).
/// Returns None if the operation exceeds TIMEOUT_SECS.
fn timed<F, R>(label: &str, f: F) -> (Option<R>, Option<f64>)
where
    F: FnOnce() -> R,
{
    let start = Instant::now();
    let result = f();
    let elapsed = start.elapsed().as_secs_f64();

    if elapsed > TIMEOUT_SECS as f64 {
        println!("  {label}: TIMEOUT (>{TIMEOUT_SECS}s)");
        (Some(result), None)
    } else {
        println!("  {label}: {elapsed:.4}s");
        (Some(result), Some(elapsed))
    }
}

fn load_query(name: &str) -> String {
    // Use Kolibrie-specific queries with fully expanded IRIs (no PREFIX declarations),
    // since Kolibrie's SPARQL parser does not support PREFIX syntax.
    let path = format!("queries/{name}.rq");
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("Failed to read {path}: {e}"))
}

fn bench_io(scale: &str, ttl_path: &str, nt_path: &str, results: &mut Vec<BenchResult>) -> Option<SparqlDatabase> {
    println!("\n{}", "=".repeat(60));
    println!("Kolibrie — {scale} dataset");
    println!("{}", "=".repeat(60));

    // --- Read Turtle ---
    let ttl_data = fs::read_to_string(ttl_path)
        .unwrap_or_else(|e| panic!("Failed to read {ttl_path}: {e}"));

    let (db_opt, t_read_ttl) = timed("Read Turtle", || {
        let mut db = SparqlDatabase::new();
        db.parse_turtle(&ttl_data);
        db
    });
    match t_read_ttl {
        Some(t) => results.push(BenchResult::ok(scale, "read_turtle", t)),
        None => {
            results.push(BenchResult::timeout(scale, "read_turtle"));
            return None;
        }
    }
    let db = db_opt.unwrap();

    // Triple count
    let count = db.triples.len();
    println!("  Triple count: {count}");

    // --- Write Turtle ---
    let out_ttl = format!("../data/{scale}_kolibrie_out.ttl");
    let (_, t_write_ttl) = timed("Write Turtle", || {
        let output = db.generate_turtle();
        fs::write(&out_ttl, output).ok();
    });
    match t_write_ttl {
        Some(t) => {
            results.push(BenchResult::ok(scale, "write_turtle", t));
            let _ = fs::remove_file(&out_ttl);
        }
        None => results.push(BenchResult::timeout(scale, "write_turtle")),
    }

    // --- Write N-Triples ---
    let out_nt = format!("../data/{scale}_kolibrie_out.nt");
    let (_, t_write_nt) = timed("Write N-Triples", || {
        let output = db.generate_ntriples();
        fs::write(&out_nt, output).ok();
    });
    match t_write_nt {
        Some(t) => {
            results.push(BenchResult::ok(scale, "write_ntriples", t));
            let _ = fs::remove_file(&out_nt);
        }
        None => results.push(BenchResult::timeout(scale, "write_ntriples")),
    }

    // --- Read N-Triples ---
    let nt_data = fs::read_to_string(nt_path)
        .unwrap_or_else(|e| panic!("Failed to read {nt_path}: {e}"));

    let (_, t_read_nt) = timed("Read N-Triples", || {
        let mut db2 = SparqlDatabase::new();
        db2.parse_ntriples_and_add(&nt_data);
        db2
    });
    match t_read_nt {
        Some(t) => results.push(BenchResult::ok(scale, "read_ntriples", t)),
        None => results.push(BenchResult::timeout(scale, "read_ntriples")),
    }

    Some(db)
}

fn bench_queries(db: &mut SparqlDatabase, scale: &str, results: &mut Vec<BenchResult>) {
    println!("\n  SPARQL queries ({scale}):");

    let query_names = [
        "q1_count",
        "q2_customer_orders",
        "q3_join_3_entities",
        "q4_optional_aggregation",
    ];

    for qname in &query_names {
        let sparql = load_query(qname);

        // Warmup run
        let (_, t_warmup) = timed(&format!("  {qname} (warmup)"), || {
            execute_query(&sparql, db)
        });
        if t_warmup.is_none() {
            println!("    {qname}: TIMEOUT");
            results.push(BenchResult::timeout(scale, &format!("query_{qname}")));
            continue;
        }

        // Best of 3
        let mut times = Vec::new();
        for _ in 0..3 {
            let start = Instant::now();
            let _ = execute_query(&sparql, db);
            let elapsed = start.elapsed().as_secs_f64();
            if elapsed > TIMEOUT_SECS as f64 {
                break;
            }
            times.push(elapsed);
        }

        if let Some(&best) = times.iter().min_by(|a, b| a.partial_cmp(b).unwrap()) {
            println!("    {qname}: {best:.4}s (best of 3)");
            results.push(BenchResult::ok(scale, &format!("query_{qname}"), best));
        } else {
            println!("    {qname}: TIMEOUT");
            results.push(BenchResult::timeout(scale, &format!("query_{qname}")));
        }
    }
}

fn main() {
    let data_dir = Path::new("../data");
    if !data_dir.exists() {
        eprintln!("ERROR: data/ directory not found at ../data");
        eprintln!("Run from the rust-kolibrie/ directory, with data/ as a sibling.");
        std::process::exit(1);
    }

    let mut results: Vec<BenchResult> = Vec::new();

    for scale in &["medium", "large", "xlarge"] {
        let ttl_path = format!("../data/{scale}.ttl");
        let nt_path = format!("../data/{scale}.nt");

        if !Path::new(&ttl_path).exists() {
            println!("\n  Skipping {scale} — {ttl_path} not found");
            continue;
        }

        let db_opt = bench_io(scale, &ttl_path, &nt_path, &mut results);

        if let Some(mut db) = db_opt {
            bench_queries(&mut db, scale, &mut results);
        } else {
            // Record TIMEOUT for all queries if I/O failed
            for qname in &[
                "q1_count",
                "q2_customer_orders",
                "q3_join_3_entities",
                "q4_optional_aggregation",
            ] {
                results.push(BenchResult::timeout(scale, &format!("query_{qname}")));
            }
        }
    }

    // Save results
    let json = serde_json::to_string_pretty(&results).expect("Failed to serialize results");
    let out_path = "../results/results_kolibrie.json";
    fs::write(out_path, json).expect("Failed to write results");
    println!("\nResults saved to {out_path}");
}
