"""Time the labels of the observations on 10,000 points. Not a unit test.

    QT_QPA_PLATFORM=offscreen python tests/bench_observation_labels.py [--points 10000] [--labels 100] [--repeat 15]
                                                                       [--scale 1.5]

It builds a scatter plot (two groups) and an XY series of ``--points`` rows, draws the canvas without any label and
then with ``--labels`` labels (the source is a text column; the limit of the series is ``--labels``), on the same
canvas of the same size, and prints one JSON document with the median, minimum and maximum of every step in
milliseconds. It also redraws with the labels of one group while the other group has none, which is the case the
rule "a series without labels pays nothing" is about, and times the Inspector steps (choosing the source, the limit,
Apply). The machine, the Qt platform, the size of the viewport and the display scale are part of the report.
``--scale`` sets ``QT_SCALE_FACTOR``: an emulated scale, not a native DPI setting. Run on a real screen (without
QT_QPA_PLATFORM=offscreen) for a screen measurement; the numbers of one machine say nothing about another one.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCATTER = "Scatter / confidence ellipse"
VIEWPORT = (1000, 700)


def summary(values):
    values = sorted(values)
    return {"median_ms": round(statistics.median(values), 2), "min_ms": round(values[0], 2),
            "max_ms": round(values[-1], 2), "n": len(values)}


def timed(function):
    start = time.perf_counter()
    result = function()
    return (time.perf_counter() - start) * 1000, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--points", type=int, default=10_000)
    parser.add_argument("--labels", type=int, default=100)
    parser.add_argument("--repeat", type=int, default=15)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    sys.path.insert(0, str(ROOT))

    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from PySide6 import __version__ as pyside
    from PySide6.QtWidgets import QApplication

    from analisi import observation_labels as ol
    from trama_qt import theme
    from trama_qt.inspector import GraphInspector
    from trama_qt.project import Project, compute

    app = QApplication.instance() or QApplication(["trama-label-bench"])
    theme.load_fonts()
    theme.apply(app)
    rng = np.random.default_rng(11)
    frame = pd.DataFrame({"X": np.arange(args.points, dtype=float), "Y": rng.normal(size=args.points).cumsum(),
                          "Group": rng.choice(["C", "T"], args.points),
                          "Name": [f"Sample {number + 1}" for number in range(args.points)]})
    folder = Path(os.environ.get("TMPDIR", "/tmp")) / "trama-label-bench"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "labels.csv"
    frame.to_csv(source, index=False)

    report = {"machine": {"platform": platform.platform(), "python": platform.python_version(), "pyside6": pyside,
                          "qt_platform": os.environ.get("QT_QPA_PLATFORM", "native"),
                          "scale": f"QT_SCALE_FACTOR={args.scale} (emulated, not a native DPI setting)"
                          if args.scale != 1.0 else "1.0 (no scaling)",
                          "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
                          "viewport_px": list(VIEWPORT), "points": args.points, "labels": args.labels,
                          "default_limit": ol.DEFAULT_LIMIT, "repeat": args.repeat},
              "cases": {}}
    cases = (("scatter_two_groups", SCATTER, {"X": "X", "Y": "Y", "Group": "Group"}),
             ("xy_line_and_points", "XY series", {"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line and points"}}))
    for name, method, recipe in cases:
        project = Project()
        title = project.load(source)[0]
        run = project.candidate(title, method, recipe)
        elapsed, result = timed(lambda: compute(run, project.tables[title].frame(mask_excluded=True)))
        index, _ = project.add_result(run, result)
        run = project.runs[index]
        canvas = FigureCanvasQTAgg(run.result.figure)
        canvas.resize(*VIEWPORT)
        canvas.draw()
        figure = run.result.figure
        case = {"calculate_ms": round(elapsed, 1)}
        case["redraw_without_labels"] = summary([timed(canvas.draw)[0] for _ in range(args.repeat)])

        elapsed, inspector = timed(lambda: GraphInspector(run, canvas, confirmed=lambda: run.style or {},
                                                          commit=lambda style: project.commit_style(run, style),
                                                          closed=lambda: None))
        case["open_inspector_ms"] = round(elapsed, 1)
        labels = inspector.labels
        series = labels.series
        case["labelled_series"] = series.key
        case["series_vertices"] = len(labels._frame()) if labels._frame() is not None else None

        def choose_source():
            combo = labels.source
            combo.setCurrentIndex(next(number for number in range(combo.count()) if combo.itemText(number) == "Name"))

        # The source is chosen: every vertex of the series is looked at once and one text is built for each label
        # that is drawn (the default limit is 250).
        case["choose_source_default_limit_ms"] = round(timed(choose_source)[0], 2)
        (status,) = [item for item in ol.label_statuses(figure) if item.state == "ok"]
        case["default_limit_drawn"] = {"shown": status.shown, "omitted": status.omitted}
        case["redraw_with_default_limit_labels"] = summary([timed(canvas.draw)[0] for _ in range(args.repeat)])

        def set_limit():
            labels.limit.setText(str(args.labels))
            labels.limit.editingFinished.emit()

        case["set_limit_ms"] = round(timed(set_limit)[0], 2)
        (status,) = [item for item in ol.label_statuses(figure) if item.state == "ok"]
        case["labels_drawn"] = {"shown": status.shown, "omitted": status.omitted, "candidates": status.candidates}
        case["redraw_with_labels"] = summary([timed(canvas.draw)[0] for _ in range(args.repeat)])
        case["texts_in_the_viewport"] = int(sum(int(layer.inside().sum()) for layer in ol.label_layers(figure)))
        case["apply_ms"] = round(timed(inspector.apply)[0], 1)
        case["redraw_after_apply"] = summary([timed(canvas.draw)[0] for _ in range(args.repeat)])
        inspector.reset_section("labels")
        inspector.apply()
        case["redraw_labels_removed"] = summary([timed(canvas.draw)[0] for _ in range(args.repeat)])
        inspector.dispose()
        report["cases"][name] = case
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
