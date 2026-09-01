"""
Shared container-memory sampler for the Docker-based benchmarks
(qlever, virtuoso, graphdb, neo4j, dotnetrdf).

A background thread polls `docker stats` for a named container and tracks the
peak memory usage. Because it polls continuously and tolerates the container
not existing yet, you can start it once and just reset()/read peak_mb per scale.

NOTE: this is CONTAINER memory (RSS of everything in the container, incl. the
JVM/DB server), a different basis than the in-process psutil RSS of the Python
engines and the JVM heap-used of the Java engines. Compare within a basis.
"""
import subprocess
import threading


def _to_mb(token):
    """Parse a docker-stats memory token like '1.5GiB' / '512MiB' / '900KiB' to MB."""
    token = token.strip()
    try:
        for unit, factor in (("GiB", 1024.0), ("GB", 1000.0),
                             ("MiB", 1.0), ("MB", 1.0),
                             ("KiB", 1 / 1024.0), ("kB", 1 / 1000.0),
                             ("B", 1 / (1024.0 * 1024.0))):
            if token.endswith(unit):
                return float(token[:-len(unit)]) * factor
    except Exception:
        pass
    return 0.0


class ContainerMemSampler:
    def __init__(self, container, interval=0.5):
        self.container = container
        self.interval = interval
        self.peak = 0.0
        self._stop = threading.Event()
        self._thread = None

    def _sample_once(self):
        # List ALL running containers and match any whose name starts with
        # self.container. This captures multi-container engines like QLever,
        # whose index builder ("<name>-index") and server ("<name>") are
        # separate containers, while still matching single-container engines.
        try:
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
                capture_output=True, text=True, timeout=15,
            )
            if out.returncode != 0:
                return
            for line in out.stdout.splitlines():
                if "\t" not in line:
                    continue
                name, usage = line.split("\t", 1)
                if name.startswith(self.container) and "/" in usage:
                    mb = _to_mb(usage.split("/")[0])
                    if mb > self.peak:
                        self.peak = mb
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def reset(self):
        self.peak = 0.0

    @property
    def peak_mb(self):
        return round(self.peak, 1) if self.peak else None
