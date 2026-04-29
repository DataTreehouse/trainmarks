"""
Benchmark: dotNetRDF — I/O and SPARQL queries via Docker (.NET 8).
Runs on medium (~100K), large (~1M), and xlarge (~10M) datasets.
Timeout: 5 minutes per operation.

dotNetRDF is a .NET/C# library for working with RDF and SPARQL.
It uses an in-memory TripleStore with the Leviathan SPARQL engine.

Prerequisites:
  - Docker installed and running
"""

import subprocess
import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
QUERIES_DIR = os.path.join(SCRIPT_DIR, "..", "queries")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "..", "results")
CONTAINER_NAME = "dotnetrdf-bench"
IMAGE_NAME = "dotnetrdf-bench"

def docker_run(args, timeout=600):
    cmd = ["docker"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def build_image():
    """Build the Docker image with the benchmark C# project."""
    print("Building Docker image...")

    # Create a Dockerfile
    dockerfile = os.path.join(SCRIPT_DIR, "Dockerfile")
    with open(dockerfile, "w") as f:
        f.write("""FROM mcr.microsoft.com/dotnet/sdk:8.0

WORKDIR /app
COPY BenchDotNetRdf.csproj .
RUN dotnet restore
COPY Program.cs .
RUN dotnet build -c Release -o /app/out

ENTRYPOINT ["dotnet", "/app/out/BenchDotNetRdf.dll"]
""")

    rc, stdout, stderr = docker_run([
        "build", "-t", IMAGE_NAME, SCRIPT_DIR
    ], timeout=900)

    if rc != 0:
        print(f"  Build failed: {stderr}")
        if stdout:
            print(f"  stdout: {stdout}")
        return False

    print("  Image built successfully")
    return True


def run_benchmark():
    """Run the benchmark container."""
    # Stop any existing container
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, timeout=30)

    print("Running benchmark...")
    print(f"  Data:    {os.path.abspath(DATA_DIR)}")
    print(f"  Queries: {os.path.abspath(QUERIES_DIR)}")
    print(f"  Results: {os.path.abspath(RESULTS_DIR)}")

    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Run with generous memory (8GB) and mount data/queries/results
    rc, stdout, stderr = docker_run([
        "run", "--rm",
        "--name", CONTAINER_NAME,
        "-m", "16g",
        "-v", f"{os.path.abspath(DATA_DIR)}:/data:ro",
        "-v", f"{os.path.abspath(QUERIES_DIR)}:/queries:ro",
        "-v", f"{os.path.abspath(RESULTS_DIR)}:/results",
        IMAGE_NAME,
    ], timeout=3600)  # 1 hour total timeout

    # Print output
    if stdout:
        print(stdout)
    if stderr:
        for line in stderr.strip().split("\n"):
            if line.strip():
                print(f"  [stderr] {line}")

    if rc != 0:
        print(f"\n  Container exited with code {rc}")
        return False

    return True


if __name__ == "__main__":
    # Check Docker
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=60, check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Docker is not available. Please install and start Docker.")
        sys.exit(1)

    if not build_image():
        sys.exit(1)

    if not run_benchmark():
        sys.exit(1)

    # Check if results were produced
    results_file = os.path.join(RESULTS_DIR, "results_dotnetrdf.json")
    if os.path.exists(results_file):
        with open(results_file) as f:
            data = json.load(f)
        print(f"\nBenchmark complete: {len(data)} results saved to results/results_dotnetrdf.json")
    else:
        print("\nWARNING: No results file found")
