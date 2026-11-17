"""Time experiment-family copies on synthetic data. Not a unit test.

    python tests/bench_family.py --tree . --runs 5                      # engine only
    xvfb-run -a -s '-screen 0 1920x1080x24' python tests/bench_family.py --tree . --runs 5 --ui

It prints one JSON document: the median, minimum and maximum of each operation in milliseconds (after a
warm-up pass), the peak Python allocation of one copy (tracemalloc, MB), the growth of the resident memory,
the name of the thread that ran the work, and with --ui the longest gap between two timer ticks of the
Tk thread while the worker copies a family (how long the interface was unresponsive).
"""
import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from uuid import UUID

import numpy as np
import pandas as pd


def rss_mb():
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * resource.getpagesize() / 1048576


def wide_family(rows=10_000, columns=30, analyses=6):
    from analisi.analysis_chain import ResultSource
    from analisi.data import Dataset
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(rng.normal(size=(rows, columns)), columns=[f"C{i}" for i in range(columns)])
    recipes = [("Transform", {"Variables": ["C0", "C1"], "Operation": "Absolute value"}),
               ("Normalize", {"Variables": ["C0", "C1"], "Method": "Subtract first value"}),
               ("Linear regression", {"X": "C0", "Y": "C1"})]
    recipes += [("Histogram", {"Response": f"C{i}", "Bins": 10}) for i in range(2, 2 + analyses - 3)]
    dataset = Dataset(frame, analyses=recipes, excluded={(i, 3) for i in range(0, rows, 97)})
    dataset.analysis_ids = {i: str(UUID(int=1000 + i)) for i in range(len(recipes))}
    dataset.analysis_sources = {1: ResultSource(dataset.analysis_ids[0], "Transformed"),
                                2: ResultSource(dataset.analysis_ids[1], "Normalized")}
    return {"Wide": dataset}


def long_chain(length=400):
    from analisi.analysis_chain import ResultSource
    from analisi.data import Dataset
    recipes = [("Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"})]
    recipes += [("Normalize", {"Variables": ["X", "Y"], "Method": "Subtract first value"})] * (length - 1)
    dataset = Dataset(pd.DataFrame({"X": [0., 1., 2., 3.], "Y": [1., 3., 5., 7.]}), analyses=recipes)
    dataset.analysis_ids = {i: str(UUID(int=5000 + i)) for i in range(length)}
    dataset.analysis_sources = {i: ResultSource(dataset.analysis_ids[i - 1], "Transformed" if i == 1 else "Normalized")
                                for i in range(1, length)}
    return {"Chain": dataset}


def timed(function, runs):
    function()
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        function()
        samples.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(statistics.median(samples), 1), "min_ms": round(min(samples), 1),
            "max_ms": round(max(samples), 1)}


def peak_mb(function):
    tracemalloc.start()
    function()
    peak = tracemalloc.get_traced_memory()[1] / 1048576
    tracemalloc.stop()
    return round(peak, 1)


def measure(tables, title, selected, runs, name):
    from analisi.family_workflow import duplicate_family, export_plan, preview_family, save_family
    where = []

    def copy():
        where.append(threading.current_thread().name)
        return duplicate_family(tables, [], [], selected, name=name)

    result = {"preview": timed(lambda: preview_family(tables, [], [], selected, name=name), runs),
              "copy": timed(copy, runs), "peak_python_mb": peak_mb(copy)}
    bundle = copy()
    result["copied_analyses"] = bundle.analysis_count
    result["copy_thread"] = where[-1]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "family.alab"
        result["save_family"] = timed(lambda: save_family(path, tables, [], [], selected), runs)
        result["file_mb"] = round(path.stat().st_size / 1048576, 2)
    result["plan_export"] = timed(lambda: export_plan(tables, [], [], selected), runs)
    return result


def ui_responsiveness(tables, selected, name, *, save=False):
    import tkinter as tk
    import tramastat
    from analisi import family_workflow_app
    from analisi.family_workflow import duplicate_family, save_family
    from analisi.theme_preferences import save_theme
    root = tk.Tk()
    with tempfile.TemporaryDirectory() as folder:
        prefs = Path(folder) / "prefs.json"
        save_theme(prefs, "standard")
        original = tramastat.config_path
        tramastat.config_path = lambda: prefs
        try:
            app = tramastat.App(root)
        finally:
            tramastat.config_path = original
        app.error = lambda error: print("error:", error, file=sys.stderr)
        app.tables.update(tables)
        app.runs.extend(app.runs_for("Wide" if "Wide" in tables else "Chain", next(iter(tables.values()))))
        ticks, stop = [], threading.Event()

        def tick():
            ticks.append(time.perf_counter())
            if not stop.is_set():
                root.after(10, tick)

        control = app.make_chain_control()
        started = []
        job_thread = []

        def job():
            job_thread.append(threading.current_thread().name)
            started.append(time.perf_counter())
            if save:
                return save_family(Path(folder) / "ui-family.alab", app.tables, app.layouts,
                                   tuple(app.info_sheets.values()), selected, cancel=control.cancel)
            return duplicate_family(app.tables, app.layouts, tuple(app.info_sheets.values()), selected, name=name,
                                    cancel=control.cancel)

        finished = []

        def done(bundle):
            finished.append(time.perf_counter())
            stop.set()
            root.after(50, root.quit)

        root.after(0, tick)
        root.after(100, lambda: app.start_family_job(job, control, running="copying", cancelled="cancelled",
                                                     failed="family.failed", finish=done,
                                                     discard_when_cancelled=True))
        root.mainloop()
        within = [b - a for a, b in zip(ticks, ticks[1:]) if started and a >= started[0] - 0.05 and b <= finished[0] + 0.05]
        app.worker.shutdown(wait=True)
        root.destroy()
    return {"job_thread": job_thread[0], "job_ms": round((finished[0] - started[0]) * 1000, 1),
            "timer_ticks_during_job": len(within), "longest_tick_gap_ms": round(max(within) * 1000, 1) if within else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", default=".")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--ui", action="store_true")
    options = parser.parse_args()
    sys.path.insert(0, str(Path(options.tree).resolve()))
    os.environ.setdefault("MPLBACKEND", "Agg")
    before = rss_mb()
    wide, chain = wide_family(), long_chain()
    report = {"python": sys.version.split()[0], "pandas": pd.__version__, "rss_before_mb": round(before, 1),
              "wide_10000x30": measure(wide, "Wide", ("data", "Wide"), options.runs, "Wide copy"),
              "chain_400": measure(chain, "Chain", ("data", "Chain"), options.runs, "Chain copy")}
    report["chain_400_graph_of_last"] = measure(chain, "Chain", ("graph", ("Chain", 399)), options.runs, "Again ")
    if options.ui:
        report["ui_wide_copy"] = ui_responsiveness(wide_family(), ("data", "Wide"), "Wide copy")
        report["ui_wide_save"] = ui_responsiveness(wide_family(), ("data", "Wide"), "", save=True)
    report["rss_after_mb"] = round(rss_mb(), 1)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
