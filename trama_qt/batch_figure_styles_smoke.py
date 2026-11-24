"""Desktop acceptance of Change → Apply style to multiple graphs…: ``python -m trama_qt.batch_figure_styles_smoke OUT``.

Runs on the real screen (or configured Qt platform) with isolated temporary preferences across
1024×768 and 1600×1000, in Italian and English, light and dark themes. Produces:
- PNG screenshots of the main window, the batch dialog with mini preview, the updated graph/layout,
  and the gallery;
- a reopenable synthetic ``.alab`` project;
- exported layout SVG before/after;
- ``metrics.json`` with timings for opening and committing 30 graphs × 1,000 points;
- ``report.txt`` and ``status.txt`` (PASS or FAIL).
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback

import numpy as np
import pandas as pd

PRESET = {
    "version": 1,
    "name": "Pubblicazione",
    "style": {"accent": "#0B7A73", "font_family": "serif", "title_size": 17, "grid": True, "legend": "upper right"},
}
SHAPE_A = {
    "id": "0b7a7300-0000-4000-8000-000000000201",
    "kind": "rectangle",
    "units": "axes",
    "points": [[0.08, 0.55], [0.30, 0.80]],
    "stroke": "#AA4433",
    "width": 1.5,
    "line_style": "dashed",
    "fill": None,
    "alpha": 1.0,
    "layer": "above",
}
SHAPE_B = {
    "id": "0b7a7300-0000-4000-8000-000000000202",
    "kind": "ellipse",
    "units": "axes",
    "points": [[0.55, 0.15], [0.85, 0.40]],
    "stroke": "#225588",
    "width": 2.0,
    "line_style": "solid",
    "fill": None,
    "alpha": 0.9,
    "layer": "above",
}


def check_in_smoke(smoke, window):
    """Inside ``python -m trama_qt --smoke``: open the batch dialog from a worksheet and check fit/clipping."""
    window.open_sheet(("data", "groups"))
    with smoke.dialogs("batch-figure-styles"):
        window.batch_figure_styles()


def _parse_runs(raw):
    if not raw:
        return [("it", "light", 1024, 768), ("en", "dark", 1024, 768),
                ("it", "dark", 1600, 1000), ("en", "light", 1600, 1000)]
    result = []
    for item in raw.split(","):
        lang, theme_name, size = item.strip().split(":")
        w, h = (int(part) for part in size.lower().split("x"))
        result.append((lang, theme_name, w, h))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--runs", default="",
                        help="Comma-separated lang:theme:WxH list (default: IT/EN, light/dark, 1024x768 & 1600x1000)")
    parser.add_argument("--skip-load", action="store_true", help="Skip the 30x1000 load measurement")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    prefs = Path(tempfile.mkdtemp(prefix="trama-batch-style-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)

    import matplotlib
    import scipy
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
    from matplotlib.colors import to_hex

    from analisi.i18n import set_language
    from analisi.layout_geometry import AUTO_PAPER, WHITE
    from analisi.legacy_restore import LEGACY_PREVIEW, LEGACY_TITLE, SAVED_BINARY_GRAPH
    from analisi.presentation import Layout, apply_style
    from . import graph_style_presets as gsp
    from . import project as project_module
    from . import theme
    from . import window as window_module
    from .batch_figure_styles_dialog import BatchFigureStylesDialog, batch_style_rows
    from .smoke import Smoke
    from .window import MainWindow

    app = QApplication.instance() or QApplication(["trama-batch-styles-smoke"])
    theme.load_fonts()
    smoke = Smoke(out)
    runs = _parse_runs(args.runs)
    metrics = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "pyside6": pyside,
        "qt_platform": app.platformName(),
        "matplotlib": matplotlib.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "runs": [],
    }
    library_path = gsp.library_path()
    gsp.PresetLibrary(library_path).save(PRESET)

    def settle():
        for _ in range(4):
            app.processEvents()
            time.sleep(0.01)

    def wait(window, timeout=120):
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()
        if window.job is not None:
            raise RuntimeError("calculation still running")

    def build_project(window):
        project = window.project
        project.add_tables({
            "Foglio Alfa": pd.DataFrame({"Dose": [1.0, 2.0, 4.0, 8.0, 16.0], "Risposta": [2.1, 3.3, 5.8, 8.1, 9.4],
                                         "Controllo": [1.9, 2.8, 4.4, 6.2, 7.5]}),
            "Foglio Beta": pd.DataFrame({"Dose": [1.0, 2.0, 4.0, 8.0, 16.0], "Risposta": [1.7, 3.0, 5.1, 7.6, 8.9],
                                         "Controllo": [1.4, 2.2, 3.9, 5.5, 6.8]}),
            "Foglio Gamma": pd.DataFrame({"X": [1.0, 2.0, 3.0, 4.0, 5.0], "Y": [2.0, 4.1, 5.9, 8.2, 9.8]}),
        })

        def calc(title, method, options, label=None):
            frame = project.tables[title].frame(mask_excluded=True)
            cand = project.candidate(title, method, options)
            if label:
                cand.label = label
            window.calculate_candidate(cand, frame, None)
            wait(window)
            return project.runs[-1]

        hom1 = calc("Foglio Alfa", "XY series",
                    {"X": "Dose", "Y columns": ["Risposta", "Controllo"], "Drawing": "Line and points"},
                    label="Curva dose")
        hom2 = calc("Foglio Beta", "XY series",
                    {"X": "Dose", "Y columns": ["Risposta", "Controllo"], "Drawing": "Line and points"},
                    label="Curva dose")
        unsel = calc("Foglio Gamma", "Linear regression", {"X": "X", "Y": "Y"})
        pending = project.candidate("Foglio Gamma", "XY series", {"X": "X", "Y columns": ["Y"]})
        pending.label = "In attesa"
        project.tables["Foglio Gamma"].analyses.append((pending.method, pending.options))
        pending.slot = len(project.tables["Foglio Gamma"].analyses) - 1
        project.runs.append(pending)
        static_opts = {LEGACY_TITLE: "Anteprima statica", LEGACY_PREVIEW: {"format": "emf", "data": ""}}
        project.tables["Foglio Gamma"].analyses.append((SAVED_BINARY_GRAPH, static_opts))
        static_run = project.runs_for("Foglio Gamma", project.tables["Foglio Gamma"])[-1]
        project.runs.append(static_run)

        from analisi.presentation import graph_series
        s1_key = graph_series(hom1.result.figure.axes[0])[1].key
        s2_key = graph_series(hom2.result.figure.axes[0])[1].key
        style1 = {"title": "Curva Alfa", "xlabel": "Dose (mg)", "ylabel": "Risposta A", "xscale": "log",
                  "axis": {"y": {"min": 0.0, "max": 12.0}}, "accent": "#AA4433", "grid": False,
                  "series": {s1_key: {"color": "#224499"}}, "shapes": [SHAPE_A]}
        style2 = {"title": "Curva Beta", "xlabel": "Dose (uM)", "ylabel": "Risposta B", "yscale": "log",
                  "accent": "#993366", "grid": False, "series": {s2_key: {"color": "#336633"}},
                  "shapes": [SHAPE_B]}
        style_u = {"title": "Regressione invariata", "accent": "#553311", "grid": False}
        for run, st in ((hom1, style1), (hom2, style2), (unsel, style_u)):
            apply_style(run.result.figure, st)
            project.commit_style(run, deepcopy(st), record_shapes=False)
        layout_idx = project.put_layout(Layout("Layout confronto", 2, [hom1.reference, hom2.reference],
                                               AUTO_PAPER, WHITE))
        project.dirty = False
        window.refresh()
        return hom1, hom2, unsel, layout_idx

    saved_project = out / "progetto-stili-blocco.alab"

    for idx, (lang, theme_name, width, height) in enumerate(runs):
        tag = f"{lang}-{theme_name}-{width}x{height}"
        smoke.language = tag
        set_language(lang)
        theme.install_qt_translations(app, lang)
        theme.apply(app, dark=theme_name == "dark")
        window = MainWindow()
        errors = []
        window.error = lambda error: errors.append(str(error))
        available = smoke.screen_rect(window)
        window.resize(min(width, available.width()), min(height, available.height()))
        window.show()
        theme.keep_on_screen(window)
        settle()
        calls = []
        run_info = {"tag": tag, "requested_size": [width, height],
                    "actual_size": [window.width(), window.height()],
                    "available_screen": [available.width(), available.height()]}
        try:
            hom1, hom2, unsel, layout_idx = build_project(window)
            window.open_sheet(("data", "Foglio Alfa"))
            smoke.expect(window.actions["batch_figure_styles"].isEnabled(),
                         f"{tag}: action disabled on data worksheet")
            window.open_sheet(("graph", 0))
            window.toggle_inspector()
            settle()
            before1, before2 = deepcopy(hom1.style), deepcopy(hom2.style)

            originals = {}
            for name in ("compute", "xy_series", "analyse"):
                for mod in (project_module, window_module):
                    if hasattr(mod, name):
                        originals[(mod, name)] = getattr(mod, name)
                        setattr(mod, name, lambda *a, _n=name, **k: calls.append(_n))

            def drive(steps):
                orig_exec = BatchFigureStylesDialog.exec

                def runner(dialog):
                    dialog.show()
                    settle()
                    steps(dialog)
                    settle()
                    return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected

                BatchFigureStylesDialog.exec = runner
                try:
                    window.batch_figure_styles()
                finally:
                    BatchFigureStylesDialog.exec = orig_exec

            try:
                # 1. Mini preview + Esc leaves everything untouched
                def cancel_step(dialog):
                    smoke.expect(not dialog.preview_image.pixmap().isNull(), f"{tag}: mini preview empty")
                    QTest.keyClick(dialog, Qt.Key.Key_Escape)

                drive(cancel_step)
                smoke.expect(hom1.style == before1 and not window.project.dirty,
                             f"{tag}: Esc mutated project")

                # 2. Apply to both homonyms
                def apply_step(dialog):
                    dialog.set_checked_uids([hom1.uid, hom2.uid])
                    settle()
                    smoke.shot(dialog, "dialog")
                    dialog.accept()

                drive(apply_step)
                smoke.expect(calls == [], f"{tag}: dispatcher called during batch apply: {calls}")
                smoke.expect(to_hex(hom1.result.figure.axes[0].lines[0].get_color()) == "#0b7a73",
                             f"{tag}: hom1 accent not applied")
                smoke.expect(to_hex(hom2.result.figure.axes[0].lines[0].get_color()) == "#0b7a73",
                             f"{tag}: hom2 accent not applied")
                smoke.expect(to_hex(unsel.result.figure.axes[0].lines[0].get_color()) == "#553311",
                             f"{tag}: unselected graph changed")
                smoke.shot(window, "graph-applied")

                window.open_sheet(("layout", layout_idx))
                settle()
                smoke.shot(window, "layout-applied")

                if idx == 0:
                    window.project.save(saved_project)
                    svg_path = out / f"{tag}-layout.svg"
                    window.project.export_layout(window.project.layouts[layout_idx], svg_path)
                    smoke.expect("#0b7a73" in svg_path.read_text(encoding="utf-8").lower(),
                                 f"{tag}: exported layout SVG missing applied accent")

                # Undo and Redo in one step
                window.actions["undo"].trigger()
                settle()
                smoke.expect(hom1.style == before1 and hom2.style == before2, f"{tag}: undo failed")
                window.actions["redo"].trigger()
                settle()
                smoke.expect(hom1.style["accent"] == "#0B7A73" and hom2.style["accent"] == "#0B7A73",
                             f"{tag}: redo failed")
                smoke.expect(calls == [], f"{tag}: dispatcher called during undo/redo: {calls}")
                smoke.expect(errors == [], f"{tag}: errors shown: {errors}")
            finally:
                for (mod, name), orig in originals.items():
                    setattr(mod, name, orig)

            # Reopen saved project on first run
            if idx == 0:
                window.open_path(saved_project)
                for g_idx in (0, 1):
                    window.open_sheet(("graph", g_idx))
                    wait(window)
                smoke.expect(window.project.runs[0].style["accent"] == "#0B7A73"
                             and window.project.runs[1].style["accent"] == "#0B7A73",
                             f"{tag}: reopened project lost batch styles")
        except Exception:  # noqa: BLE001
            smoke.problem("stopped:\n" + traceback.format_exc())
        finally:
            for session in window.sessions:
                session.project.dirty = False
            window.close()
            window.deleteLater()
            app.processEvents()
        run_info["dispatcher_calls"] = len(calls)
        metrics["runs"].append(run_info)

    # Load benchmark: 30 graphs × 1,000 points
    if not args.skip_load:
        set_language("it")
        theme.apply(app, dark=False)
        window = MainWindow()
        window.resize(1280, 800)
        window.show()
        settle()
        try:
            project = window.project
            x = np.linspace(1.0, 100.0, 1000)
            project.add_tables({f"Serie {i + 1:02d}": pd.DataFrame({"X": x, "Y": np.sin(x / (i + 2)) + i * 0.1})
                                for i in range(30)})
            for i in range(30):
                title = f"Serie {i + 1:02d}"
                run = project.candidate(title, "XY series", {"X": "X", "Y columns": ["Y"], "Drawing": "Line"})
                run.result = project_module.compute(run, project.tables[title].frame(mask_excluded=True))
                project.tables[title].analyses.append((run.method, run.options))
                run.slot = 0
                project.runs.append(run)
            window.refresh()
            window.open_sheet(("graph", 0))
            settle()
            t0 = time.perf_counter()
            rows = batch_style_rows(project)
            dialog = BatchFigureStylesDialog(window, project, rows, gsp.PresetLibrary(), current_uid=project.runs[0].uid)
            dialog.show()
            app.processEvents()
            open_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            dialog.select_all_button.click()
            dialog.accept()
            selected_uids, preset = dialog.result
            dialog.deleteLater()
            t1 = time.perf_counter()
            outcome = project.commit_style_batch(selected_uids, preset)
            commit_ms = round((time.perf_counter() - t1) * 1000.0, 2)
            window.update_actions()
            t2 = time.perf_counter()
            window.actions["undo"].trigger()
            undo_ms = round((time.perf_counter() - t2) * 1000.0, 2)
            smoke.expect(all(run.style is None for run in project.runs), "load 30x1000: undo did not revert styles")
            metrics["load_30x1000"] = {
                "graphs": 30,
                "points_per_graph": 1000,
                "changed": len(outcome.changed_uids),
                "dialog_open_ms": open_ms,
                "commit_ms": commit_ms,
                "undo_ms": undo_ms,
            }
            smoke.notes.append(f"Load 30×1000: open={open_ms} ms, commit={commit_ms} ms, undo={undo_ms} ms")
        except Exception:  # noqa: BLE001
            smoke.problem("load 30x1000 stopped:\n" + traceback.format_exc())
        finally:
            for session in window.sessions:
                session.project.dirty = False
            window.close()
            window.deleteLater()
            app.processEvents()

    screen = app.primaryScreen()
    metrics["screen"] = {
        "name": screen.name() if screen else "?",
        "available": [screen.availableGeometry().width(), screen.availableGeometry().height()] if screen else [0, 0],
        "dpr": screen.devicePixelRatio() if screen else 1.0,
        "logical_dpi": screen.logicalDotsPerInch() if screen else 96.0,
        "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    status = smoke.report()
    print(f"Batch figure styles smoke: {status} ({out})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
