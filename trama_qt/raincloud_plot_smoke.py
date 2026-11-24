"""Dedicated Qt desktop smoke for Raincloud plot:
``python -m trama_qt --smoke FOLDER --only qt-raincloud-plot``
or ``python -m trama_qt.raincloud_plot_smoke FOLDER [--dark]``.

Exercises 1024x768 and 1600x1000 layouts, English and Italian UI, light and dark
themes with isolated preferences, CSV import, conditional Bandwidth multiplier,
error focus recovery, Inspector color edit without recalculation, Format Graph,
cell exclusion, worksheet category reorder with style persistence on ``Control $``,
CSV/PNG/SVG/PDF export, 2-panel layout, and ``.alab`` save/reopen.
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
from PySide6.QtCore import Qt, qVersion  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QToolButton, QWidget  # noqa: E402

from analisi import raincloud_plot as rc  # noqa: E402
from analisi.category_order import set_order  # noqa: E402
from analisi.i18n import set_language  # noqa: E402
from analisi.presentation import compose_layout, graph_groups  # noqa: E402


def _synthetic_csv_text():
    return (
        "Gruppo,Misura\n"
        "Control $,1\n"
        "Control $,2\n"
        "Control $,2\n"
        "Control $,3\n"
        "Control $,7\n"
        "Trattamento,-1\n"
        "Trattamento,0\n"
        "Trattamento,1\n"
        "Trattamento,1\n"
        "Trattamento,1\n"
        "Trattamento,8\n"
        "Costante,4\n"
        "Costante,4\n"
        "Costante,4\n"
        "Costante,4\n"
        "Singolo,9\n"
        "Trattamento,bad\n"
        "Control $,\n"
        ",11\n"
    )


def _set_combo(dialog, field, value):
    _kind, combo = dialog.controls[field]
    idx = combo.findData(value)
    assert idx >= 0, (field, value)
    combo.setCurrentIndex(idx)


class RaincloudPlotSmoke:
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

    def _check_clipping(self, widget, name):
        for child in widget.findChildren(QWidget):
            if not child.isVisibleTo(widget) or QWidget.width(child) <= 0:
                continue
            if isinstance(child, QToolButton) and child.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly:
                continue
            if isinstance(child, QAbstractButton) and child.text():
                needed = child.minimumSizeHint().width()
            elif isinstance(child, QLabel) and child.text() and not child.wordWrap() and child.pixmap().isNull():
                needed = child.minimumSizeHint().width()
            else:
                continue
            if QWidget.width(child) + 1 < needed:
                text = child.text().replace("\n", " ")[:60]
                self.problems.append(f"[{self.language}] {name}: '{text}' width {QWidget.width(child)} < {needed}")

    def shot(self, widget, name):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        for canvas in widget.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                canvas.draw()
        self._pump(0.15)
        self._check_clipping(widget, name)
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

        csv_in = self.folder / "raincloud.csv"
        if not csv_in.exists():
            csv_in.write_text(_synthetic_csv_text(), encoding="utf-8")
        window.open_path(csv_in)
        self.wait(window)
        title = window.selected[1]
        dataset = window.project.tables[title]
        frame = dataset.frame(mask_excluded=True)

        # 1. Dialog: conditional Bandwidth multiplier, invalid input focus, then valid submission.
        dlg = AnalysisDialog(window, frame, only=[rc.METHOD], current=(rc.METHOD, {}))
        dlg.show()
        self._pump(0.1)
        _set_combo(dlg, rc.GROUP, "Gruppo")
        dlg.controls[rc.SHOW_DENSITY][1].setChecked(False)
        self._pump(0.05)
        self.expect(rc.BANDWIDTH_MULTIPLIER in dlg.hidden, f"{tag}: bandwidth should hide when density off")
        dlg.controls[rc.SHOW_DENSITY][1].setChecked(True)
        self._pump(0.05)
        self.expect(rc.BANDWIDTH_MULTIPLIER not in dlg.hidden, f"{tag}: bandwidth should show when density on")
        dlg.controls[rc.BANDWIDTH_MULTIPLIER][1].setText("0")
        dlg.accept()
        self.expect(dlg.result is None and dlg.banner.isVisible(), f"{tag}: bad bandwidth should show error")
        self.expect(dlg.error_field == rc.BANDWIDTH_MULTIPLIER, f"{tag}: wrong focus field {dlg.error_field}")
        self.shot(dlg, f"raincloud-dialog-error-{tag}-1024x768")

        dlg.controls[rc.BANDWIDTH_MULTIPLIER][1].setText("1")
        dlg.accept()
        self.expect(dlg.result is not None, f"{tag}: valid submission failed")
        method, recipe = dlg.result
        dlg.deleteLater()

        # 2. Calculate Vertical raincloud and inspect table & graph.
        cand = window.project.candidate(title, method, recipe)
        window.calculate_candidate(cand, frame, None)
        self.wait(window)
        self.expect(window.selected[0] == "graph", f"{tag}: expected graph view")
        idx = window.selected[1]
        run = window.project.runs[idx]
        result_before = run.result
        summary = run.result.tables[rc.SUMMARY_SHEET]
        self.expect(len(summary) == 4, f"{tag}: expected 4 summary rows")
        self.shot(window, f"raincloud-graph-{tag}-1024x768")

        # 3. Inspector: change Control $ color WITHOUT recalculating.
        canvas = window._figure_canvas(run.result.figure)
        inspector = GraphInspector(
            run, canvas,
            confirmed=lambda: run.style or {},
            commit=lambda style: window.commit_style(run, style, project=window.project),
            closed=lambda: None,
            parent=window,
        )
        inspector.select_group("raincloud:str:Control $")
        inspector.fields["color"].setText("#cc3311")
        inspector.fields["color"].editingFinished.emit()
        inspector.apply()
        inspector.deleteLater()
        self.expect(run.result is result_before, f"{tag}: Inspector recolor triggered unexpected recalculation")
        ctrl_now = next(g for g in graph_groups(run.result.figure.axes[0])
                        if g.key == "raincloud:str:Control $")
        scatter_now = next(a for a, role in ctrl_now.artists if role == "point")
        self.expect(abs(float(scatter_now.get_facecolor()[0][0]) - 0xCC / 255.0) < 0.02,
                    f"{tag}: Inspector recolor did not paint Control $")

        # 4. Format Graph: set title and grid while keeping group style.
        fmt = GraphFormatDialog(window, run.result.figure.axes[0], run.style or {})
        fmt.texts["title"].setText("Raincloud · Synthetic")
        fmt.grid.setChecked(True)
        fmt.accept()
        self.expect(fmt.result is not None, f"{tag}: Format Graph rejected style")
        window.project.apply_format(run, fmt.result)
        window.show_sheet(*window.selected)
        fmt.deleteLater()

        window.resize(*sizes[1])
        self._pump(0.15)
        self.shot(window, f"raincloud-graph-{tag}-1600x1000")

        window.open_sheet(("result", idx))
        self._pump(0.15)
        self.shot(window, f"raincloud-tables-{tag}-1600x1000")
        window.open_sheet(("graph", idx))
        self._pump(0.1)

        if save_artifacts:
            summary.to_csv(self.folder / f"raincloud-summary-{tag}.csv", index=False)
            for ext in ("png", "svg", "pdf"):
                out = self.folder / f"raincloud-export-{tag}.{ext}"
                export_graph(window.project.runs[idx].result.figure, out)
                self.expect(out.exists() and out.stat().st_size > 200, f"{tag}: {ext} export failed")

            # Horizontal graph for 2-panel layout.
            cand2 = window.project.candidate(title, rc.METHOD, {**recipe, rc.ORIENTATION: rc.HORIZONTAL})
            window.calculate_candidate(cand2, frame, None)
            self.wait(window)
            layout_fig = compose_layout(
                "Raincloud comparison", 2,
                [window.project.runs[0].result.figure, window.project.runs[1].result.figure],
            )
            layout_png = self.folder / f"raincloud-layout-{tag}.png"
            export_graph(layout_fig, layout_png)
            self.expect(layout_png.exists() and layout_png.stat().st_size > 200, f"{tag}: layout PNG failed")

            # Exclude cell + reorder categories, save .alab, reopen and verify style follows Control $.
            dataset.excluded.add((4, 1))
            set_order(dataset, "Gruppo", ["str:Trattamento", "str:Costante", "str:Control $", "str:Singolo"])
            window.refresh_runs([window.project.runs[0]])
            self.wait(window)

            alab = self.folder / "raincloud-plot.alab"
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
            ctrl_re = next(g for g in graph_groups(run_re.result.figure.axes[0])
                           if g.key == "raincloud:str:Control $")
            scatter_re = next(a for a, role in ctrl_re.artists if role == "point")
            self.expect(abs(float(scatter_re.get_facecolor()[0][0]) - 0xCC / 255.0) < 0.02,
                        "Control $ color did not follow group after reorder + .alab reopen")
            reopened.project.dirty = False
            reopened.close()
            self._pump(0.1)

        window.project.dirty = False
        window.close()
        self._pump(0.1)

    def execute(self):
        from . import theme
        self.app = QApplication.instance() or QApplication(["trama-raincloud-smoke"])
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
            f"Trama Raincloud plot Qt smoke: {status}",
            "--- notes ---",
            *self.notes,
        ]
        if self.problems:
            report_lines.extend(["--- problems ---", *self.problems])
        (self.folder / "report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, *, dark=False):
    return RaincloudPlotSmoke(folder, dark=dark).execute()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dedicated Qt smoke for Raincloud plot.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args(argv)
    prefs = args.folder.resolve() / "preferences"
    prefs.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = str(prefs)
    status = run(args.folder, dark=args.dark)
    print(f"Raincloud plot Qt smoke: {status} ({args.folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
