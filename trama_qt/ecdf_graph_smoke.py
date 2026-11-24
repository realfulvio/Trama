"""Dedicated Qt desktop smoke for Empirical cumulative distribution (ECDF):
``python -m trama_qt --smoke FOLDER --only qt-ecdf-graph``
or ``python -m trama_qt.ecdf_graph_smoke FOLDER [--dark]``.

Exercises 1024x768 and 1600x1000 layouts, English and Italian UI, light and dark
themes with isolated preferences, two series with ties/negative/excluded cell,
constant and empty series handling, Proportion vs Percent CSV identity, Format
Graph, live cell edit + recalculation, PNG/SVG/PDF export, and .alab save/reopen.
"""
import argparse
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback

os.environ.setdefault("MPLBACKEND", "QtAgg")

import matplotlib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import Qt, qVersion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from analisi import ecdf_graph as ecdf  # noqa: E402
from analisi.i18n import set_language  # noqa: E402


def _synthetic_frame():
    return pd.DataFrame({
        "Series A": [-1.5, 0.0, 0.0, 2.0, 3.5, 99.0],
        "Series B": [0.0, 0.0, 1.0, 1.0, 3.0, np.nan],
        "Constant": [4.0, 4.0, 4.0, 4.0, np.nan, np.nan],
        "Empty": [np.nan] * 6,
    })


def _tick_variables(dialog, *names):
    _kind, box = dialog.controls[ecdf.VARIABLES]
    for i in range(box.count()):
        box.item(i).setCheckState(Qt.CheckState.Unchecked)
    for name in names:
        for i in range(box.count()):
            if box.item(i).text() == name:
                box.item(i).setCheckState(Qt.CheckState.Checked)


def _set_combo(dialog, field, value):
    _kind, combo = dialog.controls[field]
    idx = combo.findData(value)
    assert idx >= 0, (field, value)
    combo.setCurrentIndex(idx)


class EcdfSmoke:
    def __init__(self, folder, *, dark=False):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.dark = dark
        self.problems = []
        self.notes = []
        self.language = "en"
        self.app = None
        self.window = None

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

    def wait(self, window=None, timeout=60.0):
        window = window or self.window
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
        from .window import MainWindow, export_graph

        self.language = lang
        mode_tag = "dark" if dark else "light"
        tag = f"{lang}-{mode_tag}"
        set_language(lang)
        theme.install_qt_translations(self.app, lang)
        theme.apply(self.app, dark=dark)
        self._pump(0.1)

        window = MainWindow()
        self.window = window
        window.project.dirty = False
        window.resize(*sizes[0])
        window.show()
        self._pump(0.15)

        dpr = window.devicePixelRatioF()
        screen = window.screen().geometry() if window.screen() else None
        self.note(
            f"theme={mode_tag}, size={sizes[0]}, dpr={dpr:.2f}, "
            f"platform={self.app.platformName()}, renderer={matplotlib.get_backend()}, screen={screen}"
        )

        csv_in = self.folder / f"ecdf_input_{tag}.csv"
        _synthetic_frame().to_csv(csv_in, index=False)
        window.open_path(csv_in)
        self.wait(window)
        title = window.selected[1]
        # Exclude 99.0 at row 5, col 0 (Series A)
        window.project.tables[title].excluded.add((5, 0))
        frame = window.project.tables[title].frame(mask_excluded=True)

        # 1. Dialog interaction: error banner on empty column, then valid selection with custom order
        dlg = AnalysisDialog(window, frame, current=(ecdf.METHOD, {}))
        dlg.show()
        self._pump(0.1)
        _set_combo(dlg, ecdf.INPUT, ecdf.SEPARATE)
        _tick_variables(dlg, "Series A", "Empty")
        dlg.accept()
        self.expect(dlg.result is None and dlg.banner.isVisible(), f"{tag}: empty column should show error banner")
        self.shot(dlg, f"ecdf-dialog-error-{tag}-1024x768")

        _tick_variables(dlg, "Series B", "Series A", "Constant")
        _set_combo(dlg, ecdf.Y_AXIS, ecdf.PROPORTION)
        dlg.accept()
        self.expect(dlg.result is not None, f"{tag}: valid dialog submission failed")
        method, recipe_prop = dlg.result
        self.expect(recipe_prop[ecdf.VARIABLES] == ["Series B", "Series A", "Constant"],
                    f"{tag}: selection order not preserved")
        dlg.deleteLater()

        # 2. Calculate in Proportion mode
        cand_prop = window.project.candidate(title, method, recipe_prop)
        window.calculate_candidate(cand_prop, frame, None)
        self.wait(window)
        self.expect(window.selected[0] == "graph", f"{tag}: ECDF should open on graph view")
        idx = window.selected[1]
        run_prop = window.project.runs[idx]
        self.shot(window, f"ecdf-graph-{tag}-1024x768")

        csv_prop = self.folder / f"ecdf_points_{tag}_proportion.csv"
        run_prop.result.tables[ecdf.POINTS_SHEET].to_csv(csv_prop, index=False)

        # Check artists & zero slope between jumps
        axes = run_prop.result.figure.axes[0]
        self.expect(len(axes.lines) == 3, f"{tag}: expected 3 step lines")
        self.expect(all(line.get_drawstyle() == "steps-post" for line in axes.lines),
                    f"{tag}: all lines must use steps-post")

        # 3. Switch to Percent mode, resize to 1600x1000, verify identical CSV
        recipe_pct = {**recipe_prop, ecdf.Y_AXIS: ecdf.PERCENT}
        cand_pct = window.project.candidate(title, method, recipe_pct, index=idx)
        window.calculate_candidate(cand_pct, frame, idx)
        self.wait(window)
        run_pct = window.project.runs[idx]
        self.expect(run_pct.result.figure.axes[0].get_ylabel() == "Cumulative probability (%)",
                    f"{tag}: percent ylabel mismatch")
        csv_pct = self.folder / f"ecdf_points_{tag}_percent.csv"
        run_pct.result.tables[ecdf.POINTS_SHEET].to_csv(csv_pct, index=False)
        self.expect(csv_prop.read_bytes() == csv_pct.read_bytes(),
                    f"{tag}: exported CSV differs between Proportion and Percent")

        # Format Graph check
        fmt = GraphFormatDialog(window, run_pct.result.figure.axes[0], run_pct.style or {})
        fmt.texts["title"].setText("ECDF · Synthetic comparison")
        fmt.grid.setChecked(True)
        fmt.accept()
        self.expect(fmt.result is not None, f"{tag}: Format Graph rejected valid style")
        window.project.apply_format(run_pct, fmt.result)
        window.show_sheet(*window.selected)
        fmt.deleteLater()

        window.resize(*sizes[1])
        self._pump(0.15)
        self.shot(window, f"ecdf-graph-{tag}-1600x1000")

        # Results tab screenshot
        window.open_sheet(("result", idx))
        self._pump(0.15)
        self.shot(window, f"ecdf-tables-{tag}-1600x1000")
        window.open_sheet(("graph", idx))
        self._pump(0.1)

        if save_artifacts:
            for ext in ("png", "svg", "pdf"):
                out = self.folder / f"ecdf-export-{tag}.{ext}"
                export_graph(window.project.runs[idx].result.figure, out)
                self.expect(out.exists() and out.stat().st_size > 200, f"{tag}: {ext} export failed")

            alab = self.folder / "ecdf-synthetic.alab"
            window.project.save(alab)
            self.expect(alab.exists() and alab.stat().st_size > 0, "failed to save .alab project")

            # Reopen, edit a cell, recalculate and confirm points/summary/figure update
            reopened = MainWindow()
            reopened.project.dirty = False
            reopened.resize(*sizes[0])
            reopened.show()
            reopened.open_path(alab)
            self.wait(reopened)
            reopened.open_sheet(("graph", 0))
            self.wait(reopened)
            run_re = reopened.project.runs[0]
            self.expect(run_re.options == recipe_pct, "reopened recipe mismatch")
            t_re = run_re.title
            reopened.project.tables[t_re].raw.iat[0, 0] = -4.0
            reopened.refresh_runs([run_re])
            self.wait(reopened)
            pts_re = reopened.project.runs[0].result.tables[ecdf.POINTS_SHEET]
            a_min = pts_re[pts_re["Group"] == "Series A"]["X"].iloc[0]
            fig_x = reopened.project.runs[0].result.figure.axes[0].lines[1].get_xdata()[1]
            self.expect(a_min == -4.0 and fig_x == -4.0,
                        f"recalculate after edit failed (table={a_min}, figure={fig_x})")
            reopened.project.dirty = False
            reopened.close()
            self._pump(0.1)

        window.project.dirty = False
        window.close()
        self._pump(0.1)

    def execute(self):
        from . import theme
        self.app = QApplication.instance() or QApplication(["trama-ecdf-smoke"])
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
            f"Trama ECDF Qt smoke: {status}",
            "--- notes ---",
            *self.notes,
        ]
        if self.problems:
            report_lines.extend(["--- problems ---", *self.problems])
        (self.folder / "report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, *, dark=False):
    return EcdfSmoke(folder, dark=dark).execute()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dedicated Qt smoke for Empirical cumulative distribution.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args(argv)
    prefs = args.folder.resolve() / "preferences"
    prefs.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = str(prefs)
    status = run(args.folder, dark=args.dark)
    print(f"ECDF Qt smoke: {status} ({args.folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
