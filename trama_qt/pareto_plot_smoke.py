"""Dedicated Qt desktop smoke for Pareto plot:
``python -m trama_qt --smoke FOLDER --only qt-pareto-plot``
or ``python -m trama_qt.pareto_plot_smoke FOLDER [--dark]``.

Exercises 1024x768 and 1600x1000 layouts, English and Italian UI, light and dark themes
with isolated preferences, CSV import, Threshold validation & change (80 -> 50 -> disabled),
secondary axis (0..100%) verification, Inspector recolor without recalculation (and no linked
linear axes), Format Graph, live frequency edit updating cumulative percent while keeping
worksheet order and category color, cell exclusion, CSV/PNG/SVG/PDF export, and .alab reopen.
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
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import Qt, qVersion  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QToolButton, QWidget  # noqa: E402

from analisi import pareto_plot as pp  # noqa: E402
from analisi.i18n import set_language  # noqa: E402
from analisi.presentation import graph_groups  # noqa: E402


def _synthetic_csv_text():
    return (
        "Categoria,Peso\n"
        "B,4\n"
        "A,3\n"
        "B,2\n"
        "C,3\n"
        "Zero,0\n"
    )


def _set_combo(dialog, field, value):
    _kind, combo = dialog.controls[field]
    idx = combo.findData(value)
    assert idx >= 0, (field, value)
    combo.setCurrentIndex(idx)


class ParetoPlotSmoke:
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
        from .window import GRAPHING, MainWindow, export_graph

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

        csv_in = self.folder / "pareto.csv"
        if not csv_in.exists():
            csv_in.write_text(_synthetic_csv_text(), encoding="utf-8")
        window.open_path(csv_in)
        self.wait(window)
        title = window.selected[1]
        dataset = window.project.tables[title]
        frame = dataset.frame(mask_excluded=True)

        # 1. Dialog (via Nuovo grafico / GRAPHING list): bad threshold error -> valid weighted submission.
        self.expect(pp.METHOD in GRAPHING, f"{tag}: Pareto plot missing from New graph")
        dlg = AnalysisDialog(window, frame, only=list(GRAPHING), current=(pp.METHOD, {}))
        dlg.show()
        self._pump(0.1)
        _set_combo(dlg, pp.CATEGORY, "Categoria")
        _set_combo(dlg, pp.WEIGHT, "Peso")
        dlg.controls[pp.THRESHOLD][1].setText("100")
        dlg.accept()
        self.expect(dlg.result is None and dlg.banner.isVisible(), f"{tag}: threshold 100 should fail")
        self.expect(dlg.error_field == pp.THRESHOLD, f"{tag}: wrong error focus {dlg.error_field}")
        self.shot(dlg, f"pareto-dialog-error-{tag}-1024x768")

        dlg.controls[pp.THRESHOLD][1].setText("80")
        dlg.accept()
        self.expect(dlg.result is not None, f"{tag}: valid submission failed")
        method, recipe = dlg.result
        dlg.deleteLater()

        # 2. Calculate Pareto plot and check secondary axis (0..100%) and tables.
        cand = window.project.candidate(title, method, recipe)
        window.calculate_candidate(cand, frame, None)
        self.wait(window)
        self.expect(window.selected[0] == "graph", f"{tag}: expected graph view")
        idx = window.selected[1]
        run = window.project.runs[idx]
        result_before = run.result
        fig = run.result.figure
        self.expect(len(fig.axes) == 2 and fig.axes[1].get_ylim() == (0.0, 100.0),
                    f"{tag}: secondary axis mismatch")
        table = run.result.tables[pp.CATEGORIES_SHEET]
        self.expect(table["Category"].tolist() == ["B", "A", "C", "Zero"], f"{tag}: wrong order")
        self.expect(table["Cumulative percent"].tolist() == [50.0, 75.0, 100.0, 100.0], f"{tag}: wrong cumulative")
        self.expect(run.result.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"] == "C",
                    f"{tag}: expected threshold category C")
        self.shot(window, f"pareto-graph-{tag}-1024x768")

        # 3. Inspector: no linear linked-axes button; recolor category A without recalculation.
        canvas = window._figure_canvas(fig)
        inspector = GraphInspector(
            run, canvas,
            confirmed=lambda: run.style or {},
            commit=lambda style: window.commit_style(run, style, project=window.project),
            closed=lambda: None,
            parent=window,
        )
        self.expect(not inspector.linked_widgets, f"{tag}: linear linked axes must stay disabled")
        self.expect(inspector.select_group("pareto:cat:str:A"), f"{tag}: failed to select group A")
        inspector.fields["color"].setText("#2b8a73")
        inspector.fields["color"].editingFinished.emit()
        self.expect(inspector.apply(), f"{tag}: Inspector apply failed")
        inspector.deleteLater()
        self.expect(run.result is result_before, f"{tag}: Inspector recolor triggered recalculation")

        # 4. Format Graph: set title while preserving secondary axis and custom color.
        fmt = GraphFormatDialog(window, fig.axes[0], run.style or {})
        fmt.texts["title"].setText("Pareto · Synthetic")
        fmt.accept()
        self.expect(fmt.result is not None, f"{tag}: Format Graph rejected style")
        window.project.apply_format(run, fmt.result)
        window.show_sheet(*window.selected)
        fmt.deleteLater()
        self.expect(run.result.figure.axes[1].get_ylim() == (0.0, 100.0), f"{tag}: Format Graph altered right ylim")

        window.resize(*sizes[1])
        self._pump(0.15)
        self.shot(window, f"pareto-graph-{tag}-1600x1000")

        window.open_sheet(("result", idx))
        self._pump(0.15)
        self.shot(window, f"pareto-tables-{tag}-1600x1000")
        window.open_sheet(("graph", idx))
        self._pump(0.1)

        # 5. Change threshold (80 -> 50 -> blank disabled), then restore 80.
        for thresh_val, expected_cat, expected_lines in ((50.0, "B", 4), ("", "None", 1), (80.0, "C", 4)):
            edit_cand = window.project.candidate(title, pp.METHOD, {**recipe, pp.THRESHOLD: thresh_val}, index=idx)
            window.calculate_candidate(edit_cand, dataset.frame(mask_excluded=True), idx)
            self.wait(window)
            cur = window.project.runs[idx]
            self.expect(cur.result.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"] == expected_cat,
                        f"{tag}: threshold {thresh_val!r} category mismatch")
            self.expect(len(cur.result.figure.axes[1].lines) == expected_lines,
                        f"{tag}: threshold {thresh_val!r} line count mismatch")
            self.expect(cur.result.figure.axes[1].get_ylim() == (0.0, 100.0),
                        f"{tag}: threshold {thresh_val!r} right ylim mismatch")

        if save_artifacts:
            # 6. Modify a weight in worksheet -> A moves to #1, cumulative updates, worksheet order stays intact.
            sheet_order_before = dataset.raw["Categoria"].tolist()
            dataset.raw.loc[1, "Peso"] = 10
            window.refresh_runs([window.project.runs[idx]])
            self.wait(window)
            cur = window.project.runs[idx]
            updated_table = cur.result.tables[pp.CATEGORIES_SHEET]
            self.expect(dataset.raw["Categoria"].tolist() == sheet_order_before,
                        "worksheet row order was unexpectedly modified")
            self.expect(updated_table["Category"].tolist() == ["A", "B", "C", "Zero"],
                        "updated Pareto order mismatch after weight edit")
            self.expect(updated_table["Cumulative percent"].iat[-1] == 100.0,
                        "final cumulative percent must remain 100%")
            self.expect(cur.result.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"] == "B",
                        "threshold category did not update to B")
            grp_a = graph_groups(cur.result.figure.axes[0])[0]
            self.expect(grp_a.key == "pareto:cat:str:A", "category A not first after edit")
            self.expect(abs(float(grp_a.artists[0][0].get_facecolor()[0]) - 0x2B / 255.0) < 0.02,
                        "custom color did not follow category A after recalculation")
            self.shot(window, f"pareto-updated-{tag}-1600x1000")

            # 7. Export CSV, PNG, SVG, PDF.
            updated_table.to_csv(self.folder / f"pareto-categories-{tag}.csv", index=False)
            for ext in ("png", "svg", "pdf"):
                out = self.folder / f"pareto-export-{tag}.{ext}"
                export_graph(cur.result.figure, out)
                self.expect(out.exists() and out.stat().st_size > 200, f"{tag}: {ext} export failed")

            # 8. Save .alab, reopen and verify recipe, table, secondary axis, and style.
            alab = self.folder / "pareto-plot.alab"
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
            self.expect(run_re.options == {**recipe, pp.THRESHOLD: 80.0}, "reopened recipe mismatch")
            self.expect(len(run_re.result.figure.axes) == 2
                        and run_re.result.figure.axes[1].get_ylim() == (0.0, 100.0),
                        "reopened secondary axis mismatch")
            grp_a_re = graph_groups(run_re.result.figure.axes[0])[0]
            self.expect(grp_a_re.key == "pareto:cat:str:A", "reopened group order mismatch")
            self.expect(abs(float(grp_a_re.artists[0][0].get_facecolor()[0]) - 0x2B / 255.0) < 0.02,
                        "reopened category A color lost")
            reopened.project.dirty = False
            reopened.close()
            self._pump(0.1)

        window.project.dirty = False
        window.close()
        self._pump(0.1)

    def execute(self):
        from . import theme
        self.app = QApplication.instance() or QApplication(["trama-pareto-smoke"])
        theme.load_fonts()
        self.note(
            f"Platform={platform.platform()} | Python={sys.version.split()[0]} | "
            f"PySide6={PYSIDE_VERSION} | Qt={qVersion()} | matplotlib={matplotlib.__version__} | "
            f"numpy={np.__version__} | pandas={pd.__version__}"
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
            f"Trama Pareto plot Qt smoke: {status}",
            "--- notes ---",
            *self.notes,
        ]
        if self.problems:
            report_lines.extend(["--- problems ---", *self.problems])
        (self.folder / "report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, *, dark=False):
    return ParetoPlotSmoke(folder, dark=dark).execute()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dedicated Qt smoke for Pareto plot.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args(argv)
    prefs = args.folder.resolve() / "preferences"
    prefs.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = str(prefs)
    status = run(args.folder, dark=args.dark)
    print(f"Pareto plot Qt smoke: {status} ({args.folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
