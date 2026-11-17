"""Capture the main window of the UI on the synthetic fixture of ``ui-preview/ui_fixture.json``.

Not a unit test (the name does not start with ``test_``). Run it under Xvfb whose screen size equals the
window size, one size and one scaling per run:

    xvfb-run -a -s '-screen 0 1440x900x24' python tests/capture_ui.py OUT_DIR --size 1440x900 --scale 1 --lang en

It writes ``grid.png``, ``graph.png`` and ``analyze.png`` into OUT_DIR and prints a few measurements.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tkinter as tk

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tramastat  # noqa: E402
from analisi.workbench import analyse  # noqa: E402


def fixture_frame():
    fixture = json.loads((ROOT / "ui-preview" / "ui_fixture.json").read_text(encoding="utf-8"))
    rows = fixture["rows"]
    names = ["X", "Control [1]", "Control [2]", "Treatment [1]", "Treatment [2]"]
    frame = pd.DataFrame({name: [row[i] for row in rows] for i, name in enumerate(names)}, dtype=float)
    frame.attrs.update(table_format="XY with replicates", worksheet_roles={
        "x": ["X"], "y": [["Control [1]", "Control [2]"], ["Treatment [1]", "Treatment [2]"]]})
    return frame, fixture


def grab(root, path):
    root.update_idletasks()
    root.update()
    time.sleep(0.25)
    subprocess.run(["import", "-window", "root", str(path)], check=True, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--size", default="1440x900")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--views", default="grid,graph,analyze")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    width, height = (int(part) for part in args.size.split("x"))
    tramastat.set_language(args.lang)
    root = tk.Tk()
    root.tk.call("tk", "scaling", args.scale * 96 / 72)
    app = tramastat.App(root)
    root.geometry(f"{width}x{height}+0+0")
    errors = []
    app.error = lambda error: errors.append(str(error))
    root.update()
    frame, fixture = fixture_frame()
    app._add_tables({"Replicates": frame})
    root.update()
    # The menu bar sits above the client area on Linux: shrink the window so the status bar stays on screen.
    root.geometry(f"{width}x{height - app.ribbon.winfo_rooty()}+0+0")
    grid = app.current_grid
    root.update()
    top, left, bottom, right = fixture["selection"]
    grid.select_block(top, left, bottom, right)
    for cell in fixture["excluded_cells"]:
        app.tables["Replicates"].excluded.add(tuple(cell)) if hasattr(app.tables["Replicates"], "excluded") else None
    grid.queue_draw()
    views = args.views.split(",")
    if "grid" in views:
        grab(root, out / "grid.png")
    if "graph" in views:
        method, options = "Linear regression", {"X": "X", "Y": "Control [1]", "Band": "Confidence (mean)",
                                                "Confidence level (%)": 95.0}
        from tramastat import Run
        run = Run(method, "Replicates", options)
        app.add_result(run, analyse(method, app.tables["Replicates"].raw, options))
        app.show("graph", app.runs.index(run))
        root.update()
        if app.inspector_button is not None and not app.inspector_wanted:
            app.toggle_inspector()
        grab(root, out / "graph.png")
        app.show("data", "Replicates")
    if "analyze" in views:
        dataset = app.tables["Replicates"]

        def snapshot():
            dialog = next((w for w in root.winfo_children() if isinstance(w, tramastat.AnalysisDialog)), None)
            if dialog is None:
                root.after(100, snapshot)
                return
            grab(root, out / "analyze.png")
            info = dialog.winfo_toplevel()
            print("dialog", info.winfo_width(), info.winfo_height(), "root", root.winfo_width(), root.winfo_height())
            run_button = [w for w in _walk(dialog) if isinstance(w, tk.Widget) and getattr(w, "cget", None)
                          and "text" in w.keys() and w.cget("text") == "Run Analysis"]
            if run_button:
                button = run_button[0]
                print("run analysis visible", button.winfo_rooty() + button.winfo_height() <= root.winfo_screenheight())
            dialog.cancel()

        root.after(300, snapshot)
        tramastat.AnalysisDialog(root, dataset.raw, current=("Linear regression", {
            "X": "X", "Y": "Control [1]", "Band": "Confidence (mean)", "Confidence level (%)": 120.0}),
            initial_field="Confidence level (%)",
            error="Confidence level (%) must be finite and strictly between 0 and 100.")
    print("errors", errors)
    root.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


if __name__ == "__main__":
    if not shutil.which("import"):
        raise SystemExit("ImageMagick `import` is required")
    main()
