"""
Shared timing + peak-memory helper for the Python in-process benchmarks
(maplib, maplib-disk, oxigraph, oxigraph-disk, rdflib).

`timed(label, fn)` runs fn under a SIGALRM timeout while a background thread
samples process RSS, and returns (result, seconds, peak_mb). psutil is optional:
if it is not installed, peak_mb is None and everything else still works.
"""
import gc
import os
import time
import signal
import threading

try:
    import psutil
    _PROC = psutil.Process(os.getpid())
except Exception:
    psutil = None
    _PROC = None

_HAS_ALARM = hasattr(signal, "SIGALRM")


class MemSampler:
    """Background thread sampling process RSS to capture an operation's peak."""

    def __init__(self, interval=0.1):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            if _PROC is not None:
                try:
                    rss = _PROC.memory_info().rss
                    if rss > self.peak:
                        self.peak = rss
                except Exception:
                    pass
            self._stop.wait(self.interval)

    def __enter__(self):
        if _PROC is not None:
            self.peak = _PROC.memory_info().rss
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    @property
    def peak_mb(self):
        return round(self.peak / (1024 * 1024), 1) if self.peak else None


class _Timeout(Exception):
    pass


def _handler(signum, frame):
    raise _Timeout()


def timed(label, fn, warmup=False, timeout=600):
    """Run fn under a timeout while sampling peak RSS. Returns (result, seconds, peak_mb)."""
    gc.collect()
    use_alarm = _HAS_ALARM and timeout and timeout > 0
    if use_alarm:
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
    try:
        with MemSampler() as mem:
            t0 = time.perf_counter()
            result = fn()
            elapsed = time.perf_counter() - t0
        if use_alarm:
            signal.alarm(0)
        if not warmup:
            print(f"  {label}: {elapsed:.4f}s  (peak {mem.peak_mb} MB)")
        return result, elapsed, mem.peak_mb
    except _Timeout:
        print(f"  {label}: TIMEOUT (>{timeout}s)")
        return None, None, None
    finally:
        if use_alarm:
            signal.alarm(0)
