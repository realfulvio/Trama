"""Benchmark of Cluster silhouette: time, peak memory, block size and stop latency on synthetic data.

    python tests/bench_cluster_silhouette.py                 # every scenario, table on stdout
    python tests/bench_cluster_silhouette.py --json out.json
    python tests/bench_cluster_silhouette.py --scenario near-budget --mode time    # one scenario, one measurement

Each measurement runs in a fresh interpreter so that the peak resident memory belongs to one scenario only. The data
are generated from a fixed seed. Nothing here is a test: the numbers depend on the machine they are read on.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# name -> (rows, variables, clusters, distance, standardize, graph)
SCENARIOS = {
    # N = 5 000 and p = 8: N² · p = 200 000 000, exactly the scalar budget; the graph is off above 2 000 rows.
    "near-budget": (5000, 8, 5, "Euclidean", False, False),
    "near-budget-manhattan": (5000, 8, 5, "Manhattan", True, False),
    # Many small clusters: 2 500 pairs. The reduction by cluster must not repeat the distances per cluster.
    "many-clusters": (5000, 8, 2500, "Euclidean", False, False),
    "many-clusters-wide": (4000, 12, 1000, "Euclidean", True, False),
    # The graph at its limit: 2 000 observations, 12 variables.
    "graph-limit": (2000, 12, 8, "Euclidean", False, True),
    "small": (600, 4, 3, "Euclidean", False, True),
}
# Requests the dialog must refuse before any distance array exists: name -> (rows, variables, clusters, graph).
REJECTIONS = {
    "rows over 5 000": (5001, 2, 3, False),
    "scalars over 200 000 000": (4999, 9, 3, False),
    "graph over 2 000 rows": (2001, 2, 3, True),
    "one cluster": (4000, 8, 1, False),
    "as many clusters as rows": (4000, 8, 4000, False),
    "variables over 32": (1000, 33, 3, False),
}


def hardware():
    model = cores = memory = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
        memory = next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                      if line.startswith("MemTotal"))
        memory = f"{int(memory) / 2**20:.1f} GiB"
    except (OSError, StopIteration):
        pass
    cores = os.cpu_count()
    import numpy
    import scipy
    threads = {name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
               if os.environ.get(name)}
    return {"cpu": model or platform.processor(), "logical_cpus": cores, "memory": memory,
            "system": platform.platform(), "python": platform.python_version(), "numpy": numpy.__version__,
            "scipy": scipy.__version__, "thread_env": threads}


def frame(rows, variables, clusters, seed=20261118):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    centers = rng.normal(0, 6, (clusters, variables))
    labels = np.arange(rows) % clusters
    rng.shuffle(labels)
    values = centers[labels] + rng.normal(0, 1, (rows, variables))
    data = pd.DataFrame(values, columns=[f"V{i + 1}" for i in range(variables)])
    data["Group"] = [f"g{label}" for label in labels]
    return data


def options(variables, distance="Euclidean", standardize=False, graph=False):
    return {"Variables": [f"V{i + 1}" for i in range(variables)], "Cluster": "Group", "Distance": distance,
            "Standardize": standardize, "Graph": graph}


def peak_rss_mib():
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1024 if sys.platform != "darwin" else peak / 2**20


def current_rss_mib():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.


def measure(name, mode):
    """One scenario in this interpreter. ``mode`` is time, memory or cancel."""
    sys.path.insert(0, str(ROOT))
    from analisi import cluster_silhouette as module
    from analisi.workbench import analyse
    rows, variables, clusters, distance, standardize, graph = SCENARIOS[name]
    data = frame(rows, variables, clusters)
    request = options(variables, distance, standardize, graph)
    blocks = -(-rows // module.block_rows(rows, clusters))
    report = {"scenario": name, "rows": rows, "variables": variables, "clusters": clusters, "distance": distance,
              "standardize": standardize, "graph": graph, "block_rows": module.block_rows(rows, clusters),
              "blocks": blocks, "block_bytes_limit": module.BLOCK_BYTES}
    analyse(module.METHOD, frame(60, variables, 3), options(variables))   # imports and caches are warm
    if mode == "time":
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            result = analyse(module.METHOD, data, request)
            runs.append(time.perf_counter() - start)
        mean = result.tables[module.SUMMARY]["Value"]["Mean silhouette"]
        report.update({"seconds": [round(value, 3) for value in runs], "median_seconds": round(sorted(runs)[1], 3),
                       "mean_silhouette": round(float(mean), 6)})
    elif mode == "memory":
        import tracemalloc
        baseline = current_rss_mib()
        tracemalloc.start()
        analyse(module.METHOD, data, request)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        report.update({"python_numpy_peak_mib": round(peak / 2**20, 1),
                       "input_mib": round(data.memory_usage(deep=False).sum() / 2**20, 1),
                       "process_peak_rss_mib": round(peak_rss_mib(), 1),
                       "rss_before_mib": round(baseline, 1),
                       "n_squared_float64_mib": round(rows * rows * 8 / 2**20, 1)})
    elif mode == "cancel":
        report.update(cancel_latency(module, analyse, data, request, rows, clusters))
    return report


def cancel_latency(module, analyse, data, request, rows, clusters):
    """Time from setting the event to the exception, for stops at several points of the calculation."""
    latencies, block_seconds = [], []
    real = module.cdist

    for fraction in (.15, .35, .55, .75, .9):
        calls, stamp = [], {}
        total = -(-rows // module.block_rows(rows, clusters))
        wanted = max(1, int(total * fraction))
        event = threading.Event()

        def timed(*args, **kwargs):
            begin = time.perf_counter()
            value = real(*args, **kwargs)
            block_seconds.append(time.perf_counter() - begin)
            calls.append(1)
            if len(calls) == wanted and "set" not in stamp:
                stamp["set"] = time.perf_counter()
                event.set()
            return value

        module.cdist = timed
        try:
            try:
                analyse(module.METHOD, data, request, cancel=event)
            except module.SilhouetteCancelled:
                latencies.append(time.perf_counter() - stamp["set"])
            else:
                latencies.append(float("nan"))
        finally:
            module.cdist = real
    block = sorted(block_seconds)[len(block_seconds) // 2] if block_seconds else float("nan")
    finite = [value for value in latencies if value == value]
    return {"stop_latency_ms": [round(value * 1000, 1) for value in latencies],
            "stop_latency_max_ms": round(max(finite) * 1000, 1) if finite else None,
            "median_block_ms": round(block * 1000, 1)}


def rejection(name):
    """Time and peak allocation of an early rejection. Nothing near the size of a distance array may be allocated."""
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import pandas as pd
    import tracemalloc
    from analisi import cluster_silhouette as module
    from analisi.field_error import FieldError
    rows, variables, clusters, graph = REJECTIONS[name]
    rng = np.random.default_rng(1)
    columns = max(variables, 1)
    data = pd.DataFrame(rng.normal(size=(rows, columns)), columns=[f"V{i + 1}" for i in range(columns)])
    data["Group"] = np.arange(rows) % clusters
    request = options(variables, graph=graph)
    tracemalloc.start()
    begin = time.perf_counter()
    try:
        module.check_options(data, request)
    except FieldError as error:
        refused = (error.field, str(error))
    else:
        refused = None
    elapsed = time.perf_counter() - begin
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"case": name, "rows": rows, "variables": variables, "clusters": clusters, "graph": graph,
            "field": refused[0] if refused else None, "message": refused[1] if refused else None,
            "milliseconds": round(elapsed * 1000, 1), "peak_mib": round(peak / 2**20, 2),
            "distance_array_mib": round(rows * rows * 8 / 2**20, 1)}


def run_child(*arguments):
    out = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), *arguments],
                         check=True, capture_output=True, text=True, cwd=ROOT)
    return json.loads(out.stdout)


def table(results):
    lines = ["| scenario | N | p | k | distance | scale | block rows × blocks | median s | peak NumPy MiB | peak RSS MiB | "
             "stop ms (max) | block ms |",
             "| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for item in results["scenarios"]:
        lines.append(
            f"| {item['scenario']} | {item['rows']:,} | {item['variables']} | {item['clusters']:,} | "
            f"{item['distance']} | {'standardized' if item['standardize'] else 'original'} | "
            f"{item['block_rows']} × {item['blocks']} | {item['median_seconds']} | {item['python_numpy_peak_mib']} | "
            f"{item['process_peak_rss_mib']} | {item['stop_latency_max_ms']} | {item['median_block_ms']} |")
    lines += ["", "| refused request | N | p | k | field | ms | peak MiB | distance array avoided MiB |",
              "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |"]
    for item in results["rejections"]:
        lines.append(f"| {item['case']} | {item['rows']:,} | {item['variables']} | {item['clusters']:,} | "
                     f"{item['field']} | {item['milliseconds']} | {item['peak_mib']} | "
                     f"{item['distance_array_mib']} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="one scenario only (used by the parent run)")
    parser.add_argument("--mode", choices=("time", "memory", "cancel"), default="time")
    parser.add_argument("--rejection", choices=sorted(REJECTIONS))
    parser.add_argument("--json", help="write the whole report here")
    arguments = parser.parse_args()
    if arguments.rejection:
        print(json.dumps(rejection(arguments.rejection)))
        return
    if arguments.scenario:
        print(json.dumps(measure(arguments.scenario, arguments.mode)))
        return
    results = {"hardware": hardware(), "scenarios": [], "rejections": []}
    for name in SCENARIOS:
        merged = {}
        for mode in ("time", "memory", "cancel"):
            merged.update(run_child("--scenario", name, "--mode", mode))
            print(f"{name} {mode} done", file=sys.stderr)
        results["scenarios"].append(merged)
    for name in REJECTIONS:
        results["rejections"].append(run_child("--rejection", name))
    print(json.dumps(results["hardware"], indent=2))
    print(table(results))
    if arguments.json:
        Path(arguments.json).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
