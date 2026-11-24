"""Time single-point formatting on 10,000 points. Not a unit test.

    QT_QPA_PLATFORM=offscreen python tests/bench_point_style.py [--points 10000] [--edits 100] [--scale 1.5]

It builds a scatter plot and an XY series of ``--points`` rows, opens the Graph Inspector on each, picks a point and
makes ``--edits`` edits through the real fields (each edit validates, previews with ``apply_style`` and, as the
screen does, redraws the canvas with the Agg renderer). It prints one JSON document with the median, minimum and
maximum of every step in milliseconds, the same figures for the same redraw without any point style, and what the
measurement is: the machine, the Qt platform and the display scale. ``--scale`` sets ``QT_SCALE_FACTOR``: an
emulated scale, not a native DPI setting. Run on a real screen (without QT_QPA_PLATFORM=offscreen) for a screen
measurement; the numbers of one machine say nothing about another one.
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
    parser.add_argument("--edits", type=int, default=100)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    sys.path.insert(0, str(ROOT))

    from matplotlib.backend_bases import MouseEvent
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from PySide6 import __version__ as pyside
    from PySide6.QtWidgets import QApplication

    from analisi import point_style as ps
    from trama_qt import theme
    from trama_qt.inspector import GraphInspector
    from trama_qt.project import Project, compute

    app = QApplication.instance() or QApplication(["trama-point-bench"])
    theme.load_fonts()
    theme.apply(app)
    rng = np.random.default_rng(11)
    frame = pd.DataFrame({"X": np.arange(args.points, dtype=float),
                          "Y": rng.normal(size=args.points).cumsum(),
                          "Group": rng.choice(["C", "T"], args.points)})
    folder = Path(os.environ.get("TMPDIR", "/tmp")) / "trama-point-bench"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "points.csv"
    frame.to_csv(source, index=False)

    report = {"machine": {"platform": platform.platform(), "python": platform.python_version(), "pyside6": pyside,
                          "qt_platform": os.environ.get("QT_QPA_PLATFORM", "native"),
                          "scale": f"QT_SCALE_FACTOR={args.scale} (emulated, not a native DPI setting)"
                          if args.scale != 1.0 else "1.0 (no scaling)",
                          "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
                          "points": args.points, "edits": args.edits},
              "cases": {}}
    cases = (("scatter", SCATTER, {"X": "X", "Y": "Y"}),
             ("xy_line_and_points", "XY series", {"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line and points"}}))
    for name, method, recipe in cases:
        project = Project()
        title = project.load(source)[0]
        run = project.candidate(title, method, recipe)
        elapsed, result = timed(lambda: compute(run, project.tables[title].frame(mask_excluded=True)))
        index, _ = project.add_result(run, result)
        run = project.runs[index]
        canvas = FigureCanvasQTAgg(run.result.figure)
        canvas.resize(1000, 700)
        canvas.draw()
        figure = run.result.figure
        case = {"calculate_ms": round(elapsed, 1)}

        # Baseline: the same redraw with no point style at all.
        case["redraw_without_point_styles"] = summary([timed(canvas.draw)[0] for _ in range(10)])

        elapsed, inspector = timed(lambda: GraphInspector(run, canvas, confirmed=lambda: run.style or {},
                                                          commit=lambda style: project.commit_style(run, style),
                                                          closed=lambda: None))
        case["open_inspector_ms"] = round(elapsed, 1)
        points = inspector.points
        series = points.series
        case["list_rows"] = points.model.rowCount()
        case["list_first_page_ms"] = round(timed(lambda: [points.model.data(points.model.index(row))
                                                          for row in range(40)])[0], 2)

        # Picking: a click on the graph, 10,000 vertices measured in display pixels.
        axes = inspector.axes
        pmap = ps.point_map(series.artist)
        target = int(len(pmap) // 2)
        px, py = axes.transData.transform((pmap.x[target], pmap.y[target]))
        clicks = []
        for _ in range(20):
            event = MouseEvent("button_press_event", canvas, px, py, button=1)
            clicks.append(timed(lambda event=event: canvas.callbacks.process("button_press_event", event))[0])
        case["click_to_select"] = summary(clicks)
        case["selected_row"] = None if points.vertex is None else int(pmap.rows[points.vertex])

        # The edits: each one changes a field of the selected point (the same point) and redraws the canvas.
        colors = ("#ac4320", "#2b8a73")
        edit, redraw, total = [], [], []
        for number in range(args.edits):
            def one(number=number):
                points.color.setText(colors[number % 2])
                points.color.editingFinished.emit()

            start = time.perf_counter()
            elapsed_edit, _ = timed(one)
            elapsed_draw, _ = timed(canvas.draw)
            total.append((time.perf_counter() - start) * 1000)
            edit.append(elapsed_edit)
            redraw.append(elapsed_draw)
        case["edit_preview"] = summary(edit)
        case["edit_redraw"] = summary(redraw)
        case["edit_total"] = summary(total)
        case["records_after_edits"] = len(inspector.draft.get(ps.POINTS, []))

        # 100 different points, one record each (a harder case: the list of formatted points grows).
        inspector.reset_section("points")
        inspector.discard()
        vertices = np.linspace(0, len(pmap) - 1, args.edits, dtype=int)
        grow, grow_draw = [], []
        for vertex in vertices:
            points.select(series, int(vertex))
            elapsed_edit, _ = timed(lambda: (points.color.setText("#ac4320"), points.color.editingFinished.emit()))
            elapsed_draw, _ = timed(canvas.draw)
            grow.append(elapsed_edit)
            grow_draw.append(elapsed_draw)
        case["distinct_points_preview"] = summary(grow)
        case["distinct_points_redraw"] = summary(grow_draw)
        case["records_after_distinct_points"] = len(inspector.draft.get(ps.POINTS, []))
        statuses = ps.point_statuses(figure)
        case["all_resolved"] = all(status.ok for status in statuses)
        case["apply_ms"] = round(timed(inspector.apply)[0], 1)
        case["redraw_with_100_styled_points"] = summary([timed(canvas.draw)[0] for _ in range(10)])
        inspector.dispose()
        report["cases"][name] = case
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
