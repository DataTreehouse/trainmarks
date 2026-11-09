# Constrained-memory test — in-memory maplib

A quick experiment to see how the **in-memory** maplib engine (as benchmarked in
`../python-maplib/`) behaves when it's given less RAM than it wants.

macOS has no reliable per-process RAM cap (`ulimit -v` is effectively ignored for
Arrow/mmap-heavy processes), so this runs the same read/query workload inside a
Docker container with a **hard `--memory` limit**. If maplib tries to exceed the
cap, the kernel OOM-kills the container (exit code 137). Results are saved after
every operation, so a kill still leaves a partial JSON showing exactly how far it
got before running out.

## Run

```bash
# from this folder — Docker must be running
bash run_memcap.sh 4g                 # 4 GB cap, all scales
bash run_memcap.sh 2g large,xlarge    # 2 GB cap, 1M + 10M only
bash run_memcap.sh 1g xlarge          # 1 GB cap, 10M only
```

Lower the cap until a scale OOM-kills, to find maplib's in-memory floor for that
data size. Each cap writes `./results/results_maplib_memcap_<cap>.json` **inside
this folder** — the main `../results/` benchmark data is never touched.

## Caveats

- Uses the **open-source in-memory maplib** installed via pip (a Linux container
  can't run the licensed macOS disk-backed wheel). The exact version is printed
  at the top of the run log. This is a *behavioral* test, so a small version
  difference from your local 0.20.29 is fine.
- `--memory-swap` is pinned equal to `--memory`, so the container cannot spill to
  swap — the cap is real.
- Container memory is the whole process (Python + maplib + Arrow), so the OOM
  point is a bit above the pure store size. That's the point: it's the total
  footprint that has to fit.
