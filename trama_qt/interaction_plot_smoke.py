"""Dedicated Qt desktop smoke for Interaction plot:
``python -m trama_qt --smoke FOLDER --only qt-interaction-plot``
or ``python -m trama_qt.interaction_plot_smoke FOLDER [--dark]``.

Exercises 1024x768 and 1600x1000 layouts, English and Italian UI, light and dark
themes with isolated preferences, CSV import, role validation error recovery with
selection/focus preservation, Inspector & Format Graph series styling, live edit
(2 -> 8 -> mean 4 -> 6) and cell exclusion (mean 5, N=2) with series style
persistence, CSV/PNG/SVG/PDF export, 2-panel layout, and .alab save/reopen.
"""
import argparse
import os
from pathlib import Path
import platform
import sys
import time
import traceback

os.environ.setdefault("MPLBACKEND", "QtAgg")

import matplotlib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import qVersion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from analisi import interaction_plot as ip  # noqa: E402
from analisi.grid_data import edit_cell_value  # noqa: E402
from analisi.i18n import set_language  # noqa: E402
from analisi.presentation import compose_layout, graph_series  # noqa: E402


def _synthetic_csv_text():
    return (
        "Dose,Group,Response\n"
        "Low,Control $,2\n"
        "Low,Control $,4\n"
        "Low,Control $,6\n"
        "Low,Treatment,6\n"
        "Low,Treatment,10\n"
        "Mid,Control $,5\n"
        "Mid,Control $,7\n"
        "Mid,Treatment,\n"
        "High,Control $,9\n"
        "High,Treatment,12\n"
        "High,Treatment,12\n"
        "Low,Control $,inf\n"
        "High,Treatment,bad\n"
        ",Control $,32\n"
        "High,,40\n"
    )


def _set_combo(dialog, field, value):
    _kind, combo = dialog.controls[field]
    idx = combo.findData(value)
    assert idx >= 0, (field, value)
    combo.setCurrentIndex(idx)


class InteractionPlotSmoke:
    def __init__(self, folder, *, dark=False):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.dark = dark
        self.problems = []
        self.notes = []
        self.language = "en"
        self.app = None

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def expect(self, condition, text):
        if not condition:
            self.problems.append(f"[{self.language}] {text}")
        return bool(condition)

    def _pump(self, seconds=0.12):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def wait(self, window, timeout=60.0):
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.expect(window.job is None, "calculation did not finish in time")

    def shot(self, widget, name):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        for canvas in widget.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                canvas.draw()
        self._pump(0.15)
        target = self.folder / f"{name}.png"
        ok = widget.grab().save(str(target))
        self.expect(ok and target.exists() and target.stat().st_size > 0, f"failed to capture {target.name}")

    def run_pass(self, lang, *, dark=False, sizes=((1024, 768), (1600, 1000)), save_artifacts=False):
        from . import theme
        from .analysis_dialog import AnalysisDialog
        from .graph_format import GraphFormatDialog
        from .inspector import GraphInspector
        from .window import MainWindow, export_graph

        self.language = lang
        mode_tag = "dark" if dark else "light"
        tag = f"{lang}-{mode_tag}"
        set_language(lang)
        theme.STATE["mode"] = "dark" if dark else "light"
        theme.apply(self.app)

        window = MainWindow()
        window.project.dirty = False
        window.resize(*sizes[0])
        window.show()
        self._pump(0.15)

        csv_in = self.folder / "interaction.csv"
        if not csv_in.exists():
            csv_in.write_text(_synthetic_csv_text(), encoding="utf-8")
        window.open_path(csv_in)
        self.wait(window)
        title = window.selected[1]
        frame = window.project.tables[title].frame(mask_excluded=True)

        # 1. Dialog: open via Graphing subset (as New graph… does), trigger duplicate role error, verify selection & focus.
        dlg = AnalysisDialog(window, frame, only=[ip.METHOD], current=(ip.METHOD, {}))
        dlg.show()
        self._pump(0.1)
        _set_combo(dlg, ip.SERIES_FACTOR, "Dose")
        dlg.controls[ip.CONFIDENCE_LEVEL][1].setText("90")
        dlg.accept()
        self.expect(dlg.result is None and dlg.banner.isVisible(), f"{tag}: duplicate role should show error banner")
        self.expect(dlg.error_field == ip.SERIES_FACTOR, f"{tag}: wrong error field {dlg.error_field}")
        self.expect(dlg.controls[ip.CONFIDENCE_LEVEL][1].text() == "90", f"{tag}: confidence input lost after error")
        self.shot(dlg, f"interaction-dialog-error-{tag}-1024x768")

        _set_combo(dlg, ip.SERIES_FACTOR, "Group")
        dlg.controls[ip.CONFIDENCE_LEVEL][1].setText("95")
        dlg.accept()
        self.expect(dlg.result is not None, f"{tag}: valid dialog submission failed")
        method, recipe = dlg.result
        dlg.deleteLater()

        # 2. Calculate and inspect table & graph.
        cand = window.project.candidate(title, method, recipe)
        window.calculate_candidate(cand, frame, None)
        self.wait(window)
        self.expect(window.selected[0] == "graph", f"{tag}: expected graph view")
        idx = window.selected[1]
        run = window.project.runs[idx]
        cells = run.result.tables[ip.CELLS_SHEET]
        self.expect(abs(float(cells.iloc[0]["Mean"]) - 4.0) < 1e-9, f"{tag}: initial mean != 4")
        self.shot(window, f"interaction-graph-{tag}-1024x768")

        # 3. Inspector + Format Graph series style.
        canvas = window._figure_canvas(run.result.figure)
        inspector = GraphInspector(
            run, canvas,
            confirmed=lambda: run.style or {},
            commit=lambda style: window.commit_style(run, style, project=window.project),
            closed=lambda: None,
            parent=window,
        )
        inspector.fields["color"].setText("#cc3311")
        inspector.apply()
        inspector.deleteLater()

        fmt = GraphFormatDialog(window, run.result.figure.axes[0], run.style or {})
        fmt.texts["title"].setText("Interaction · Synthetic")
        fmt.grid.setChecked(True)
        fmt.accept()
        self.expect(fmt.result is not None, f"{tag}: Format Graph rejected style")
        style = dict(fmt.result)
        style.setdefault("series", {})["errorbar:1:Control $"] = {"color": "#cc3311", "marker": "D", "width": 2.4}
        window.project.apply_format(run, style)
        window.show_sheet(*window.selected)
        fmt.deleteLater()

        window.resize(*sizes[1])
        self._pump(0.15)
        self.shot(window, f"interaction-graph-{tag}-1600x1000")

        window.open_sheet(("result", idx))
        self._pump(0.15)
        self.shot(window, f"interaction-tables-{tag}-1600x1000")
        window.open_sheet(("graph", idx))
        self._pump(0.1)

        if save_artifacts:
            # Export CSV + PNG/SVG/PDF.
            cells.to_csv(self.folder / f"interaction-cells-{tag}.csv", index=False)
            for ext in ("png", "svg", "pdf"):
                out = self.folder / f"interaction-export-{tag}.{ext}"
                export_graph(window.project.runs[idx].result.figure, out)
                self.expect(out.exists() and out.stat().st_size > 200, f"{tag}: {ext} export failed")

            # Second graph for 2-panel layout export.
            cand2 = window.project.candidate(title, ip.METHOD, {**recipe, ip.ERROR_BARS: ip.NONE})
            window.calculate_candidate(cand2, frame, None)
            self.wait(window)
            layout_fig = compose_layout(
                "Interaction comparison", 2,
                [window.project.runs[0].result.figure, window.project.runs[1].result.figure],
            )
            layout_png = self.folder / f"interaction-layout-{tag}.png"
            export_graph(layout_fig, layout_png)
            self.expect(layout_png.exists() and layout_png.stat().st_size > 200, f"{tag}: layout PNG failed")

            # Save .alab, reopen, edit first 2 -> 8 (mean 4 -> 6), exclude cell (mean 5, N=2).
            alab = self.folder / "interaction-plot.alab"
            window.project.save(alab)
            self.expect(alab.exists() and alab.stat().st_size > 0, "failed to save .alab")

            reopened = MainWindow()
            reopened.project.dirty = False
            reopened.resize(*sizes[0])
            reopened.show()
            reopened.open_path(alab)
            self.wait(reopened)
            reopened.open_sheet(("graph", 0))
            self.wait(reopened)
            run_re = reopened.project.runs[0]
            self.expect(run_re.options == recipe, "reopened recipe mismatch")

            edit_cell_value(reopened.project.tables[title], 0, 2, "8")
            reopened.refresh_runs([run_re])
            self.wait(reopened)
            edited = reopened.project.runs[0].result.tables[ip.CELLS_SHEET]
            self.expect(abs(float(edited.iloc[0]["Mean"]) - 6.0) < 1e-9, "edit 2->8 did not yield mean 6")

            reopened.project.tables[title].excluded.add((0, 2))
            reopened.refresh_runs([reopened.project.runs[0]])
            self.wait(reopened)
            excl = reopened.project.runs[0].result.tables[ip.CELLS_SHEET]
            self.expect(abs(float(excl.iloc[0]["Mean"]) - 5.0) < 1e-9 and int(excl.iloc[0]["N"]) == 2,
                        "exclude cell did not yield mean 5 and N=2")
            ctrl_s = next(s for s in graph_series(reopened.project.runs[0].result.figure.axes[0])
                          if s.key == "errorbar:1:Control $")
            self.expect(ctrl_s.artist.lines[0].get_color() == "#cc3311",
                        "series style did not persist after edit and exclusion")

            reopened.project.dirty = False
            reopened.close()
            self._pump(0.1)

        window.project.dirty = False
        window.close()
        self._pump(0.1)

    def execute(self):
        from . import theme
        self.app = QApplication.instance() or QApplication(["trama-interaction-smoke"])
        theme.load_fonts()
        self.note(
            f"Platform={platform.platform()} | Python={sys.version.split()[0]} | "
            f"PySide6={PYSIDE_VERSION} | Qt={qVersion()} | matplotlib={matplotlib.__version__} | "
            f"numpy={np.__version__} | pandas={pd.__version__} | scipy={scipy.__version__}"
        )
        try:
            self.run_pass("en", dark=False, save_artifacts=True)
            self.run_pass("it", dark=False, save_artifacts=False)
            self.run_pass("it", dark=True, save_artifacts=False)
            if self.dark:
                self.run_pass("en", dark=True, save_artifacts=False)
        except Exception:
            self.problems.append(traceback.format_exc())
        status = "PASS" if not self.problems else "FAIL"
        report_lines = [
            f"Trama Interaction plot Qt smoke: {status}",
            "--- notes ---",
            *self.notes,
        ]
        if self.problems:
            report_lines.extend(["--- problems ---", *self.problems])
        (self.folder / "report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, *, dark=False):
    return InteractionPlotSmoke(folder, dark=dark).execute()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dedicated Qt smoke for Interaction plot.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args(argv)
    prefs = args.folder.resolve() / "preferences"
    prefs.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = str(prefs)
    status = run(args.folder, dark=args.dark)
    print(f"Interaction plot Qt smoke: {status} ({args.folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
