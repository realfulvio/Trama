"""Benchmark of Reshape long and wide: ``python tests/perf_reshape_long_wide.py [OUTPUT.json]``.

A synthetic 50,000 × 20 worksheet (ID, 19 numeric measures with 2% blanks). It times the import of the engine,
the preview, the calculation (the work of the Qt worker), the cancellation latency (the time from the cancel
request to the end of the call, with the request sent while the calculation runs) and the CSV export, and
measures the Python memory peak of the calculation with tracemalloc (numpy and pandas buffers included).
Cases: Wide to long with 9 measures (inside the 2,000,000-cell budget), Long to wide on that result, a 50,000-row
long table to 2,500 × 21, and Wide to long with all 19 measures (over budget: refused by the preview and by the
calculation before anything is allocated).
"""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

started = time.perf_counter()
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analisi import reshape_long_wide as rl  # noqa: E402
from analisi.field_error import FieldError  # noqa: E402
from analisi.workbench import analyse  # noqa: E402

IMPORT_SECONDS = time.perf_counter() - started
METHOD = "Reshape long and wide"


def worksheet(rows=50_000, measures=19, seed=96):
    rng = np.random.default_rng(seed)
    data = {"Sample $": [f"{n:06d}" for n in range(rows)]}
    for column in range(measures):
        values = rng.normal(10, 2, rows)
        values[rng.random(rows) < 0.02] = np.nan
        data[f"M{column + 1} | µg"] = values
    return pd.DataFrame(data)


def timed(function, repeat=3):
    best = None
    for _ in range(repeat):
        start = time.perf_counter()
        value = function()
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best, value


def peak(function):
    tracemalloc.start()
    try:
        value = function()
        _, top = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return top, value


def cancel_latency(frame, options, delay):
    event = threading.Event()
    outcome = {}

    def work():
        try:
            analyse(METHOD, frame, options, cancel=event)
            outcome["state"] = "finished"
        except rl.ReshapeCancelled:
            outcome["state"] = "cancelled"
        outcome["end"] = time.perf_counter()

    thread = threading.Thread(target=work)
    thread.start()
    time.sleep(delay)
    requested = time.perf_counter()
    event.set()
    thread.join()
    return outcome["state"], max(0.0, outcome["end"] - requested)


def case(name, frame, options, folder):
    record = {"case": name, "input": list(frame.shape), "options": options}
    try:
        record["preview_s"], shown = timed(lambda: rl.preview(frame, options))
        record["result_shape"] = [shown.rows, shown.columns]
    except FieldError as error:
        record["preview_s"], record["refused"] = None, str(error)
        start = time.perf_counter()
        try:
            analyse(METHOD, frame, options)
        except FieldError as again:
            record["run_refused_s"] = time.perf_counter() - start
            record["run_refused"] = str(again)
        return record, None
    record["run_s"], result = timed(lambda: analyse(METHOD, frame, options))
    record["peak_mib"] = round(peak(lambda: analyse(METHOD, frame, options))[0] / 2 ** 20, 1)
    state, latency = cancel_latency(frame, options, record["run_s"] / 3)
    record["cancel"] = {"state": state, "latency_s": latency}
    path = Path(folder) / f"{name}.csv"
    record["export_s"], _ = timed(lambda: result.tables["Reshaped data"].to_csv(path, index=False), repeat=1)
    record["export_mib"] = round(path.stat().st_size / 2 ** 20, 1)
    return record, result.tables["Reshaped data"]


def main():
    wide = worksheet()
    measures = [column for column in wide.columns if column != "Sample $"]
    records = []
    with tempfile.TemporaryDirectory() as folder:
        lengthen = {"Direction": "Wide to long", "ID columns": ["Sample $"], "Measure columns": measures[:9],
                    "Output names": "Measure", "Output values": "Value"}
        record, long = case("wide-to-long-50000x10", wide, lengthen, folder)
        records.append(record)
        widen = {"Direction": "Long to wide", "ID columns": ["Sample $"], "Name column": "Measure",
                 "Value column": "Value"}
        records.append(case("long-to-wide-450000", long, widen, folder)[0])
        subjects = pd.DataFrame({"Subject": np.repeat(np.arange(2_500), 20),
                                 "Visit": np.tile([f"V{n:02d}" for n in range(20)], 2_500),
                                 **{column: wide[column] for column in measures[:18]}})
        records.append(case("long-to-wide-50000x20", subjects, {"Direction": "Long to wide", "ID columns": ["Subject"],
                                                                "Name column": "Visit", "Value column": measures[0]},
                            folder)[0])
        over = dict(lengthen, **{"Measure columns": measures})
        records.append(case("wide-to-long-over-budget", wide, over, folder)[0])
    report = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
              "cpu": platform.processor() or platform.machine(), "cpus": os.cpu_count(),
              "mode": "single thread (Qt worker thread), no process pool",
              "import_s": IMPORT_SECONDS, "cases": records}
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
