"""Time the worksheet on a synthetic 10,000 x 30 grid: open, select, scroll, paste.

Not a unit test. Run it under Xvfb, once per source tree, in the same environment:

    xvfb-run -a -s '-screen 0 1440x900x24' python tests/bench_grid.py --tree . --runs 7

It prints one JSON line with the median, minimum and maximum of each operation in milliseconds (after one
warm-up pass) and the resident memory in MB before, after the first table is open and at the end.
"""
import argparse
import json
from pathlib import Path
import resource
import statistics
import sys
import time
import tkinter as tk

import numpy as np
import pandas as pd


def rss_mb():
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * resource.getpagesize() / 1048576


def settle(root):
    root.update_idletasks()
    root.update()


def timed(root, action):
    start = time.perf_counter()
    action()
    settle(root)
    return (time.perf_counter() - start) * 1000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", default=".")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--size", default="1440x900")
    args = parser.parse_args()
    tree = Path(args.tree).resolve()
    sys.path.insert(0, str(tree))
    import tramastat
    tramastat.set_language("en")
    width, height = (int(part) for part in args.size.split("x"))
    root = tk.Tk()
    app = tramastat.App(root)
    root.geometry(f"{width}x{height}+0+0")
    app.error = lambda error: print("error", error, file=sys.stderr)
    settle(root)
    before = rss_mb()
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(rng.normal(size=(10000, 30)).round(3), columns=[f"Y{i + 1}" for i in range(30)])
    clip = "\n".join("\t".join(f"{value:.3f}" for value in row) for row in rng.normal(size=(200, 10)))
    results = {"open table": [], "select block": [], "scroll 100 steps": [], "scroll to end": [], "paste 200x10": []}
    # The first pass warms caches and fonts; its numbers are discarded.
    for run in range(args.runs + 1):
        name = f"Bench {run}"
        results_run = {}
        results_run["open table"] = timed(root, lambda: app._add_tables({name: frame.copy()}))
        grid = app.current_grid
        settle(root)
        results_run["select block"] = timed(root, lambda: grid.select_block(10, 2, 400, 12))

        def scroll():
            for _ in range(100):
                grid.wheel_rows(3)
                root.update_idletasks()

        results_run["scroll 100 steps"] = timed(root, scroll)
        results_run["scroll to end"] = timed(root, lambda: grid.canvas.yview_moveto(1.0))
        grid.canvas.yview_moveto(0.0)
        grid.select_block(5, 1, 5, 1)
        settle(root)
        root.clipboard_clear()
        root.clipboard_append(clip)
        results_run["paste 200x10"] = timed(root, app.paste_selection)
        if run == 0:
            first = rss_mb()
        if run:
            for key, value in results_run.items():
                results[key].append(value)
    summary = {key: {"median": round(statistics.median(v), 1), "min": round(min(v), 1), "max": round(max(v), 1)}
               for key, v in results.items()}
    print(json.dumps({"tree": str(tree), "runs": args.runs, "rss_before_mb": round(before, 1),
                      "rss_first_table_mb": round(first, 1), "rss_end_mb": round(rss_mb(), 1), "ms": summary}))
    root.destroy()


if __name__ == "__main__":
    main()
