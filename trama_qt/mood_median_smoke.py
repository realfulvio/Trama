"""Qt smoke for Mood's median test.

``python -m trama_qt.mood_median_smoke FOLDER`` or
``python -m trama_qt --smoke FOLDER --only qt-mood-median``.

Real window, isolated preferences. English light drives the field error; Italian
covers captions; both window sizes; one dark pass; Ties/Yates change; a cell edit;
CSV export; a reopened ``.alab``; and the no-inference Ignore path. Evidence stays
in FOLDER.
"""
import argparse
import os
from pathlib import Path
import platform
import sys
import time
import traceback
from unittest import mock

os.environ.setdefault("MPLBACKEND", "QtAgg")

import matplotlib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog  # noqa: E402

from analisi import mood_median as mood  # noqa: E402
from analisi.i18n import set_language  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent / "tests" / "data" / "mood_median" / "mood.csv"


def _check_columns(dialog, names):
    box = dialog.controls[mood.VARIABLES][1]
    wanted = set(names)
    for index in range(box.count()):
        item = box.item(index)
        item.setCheckState(Qt.CheckState.Checked if item.text() in wanted else Qt.CheckState.Unchecked)


def _fill(dialog, *, columns=None, ties=None, yates=None):
    if columns is not None:
        _check_columns(dialog, columns)
    if ties is not None:
        control = dialog.controls[mood.TIES][1]
        index = control.findData(ties)
        assert index >= 0, ties
        control.setCurrentIndex(index)
    if yates is not None and dialog.controls[mood.YATES][1].isEnabled():
        dialog.controls[mood.YATES][1].setChecked(bool(yates))


class MoodMedianSmoke:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
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

    def _pump(self, seconds=0.15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def wait(self, window=None, timeout=60):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.expect(window.job is None, "calculation did not finish in time")

    def shot(self, widget, name):
        self._pump(0.15)
        target = self.folder / f"{name}.png"
        ok = widget.grab().save(str(target))
        self.expect(ok and target.exists() and target.stat().st_size > 0, f"failed to capture {target.name}")

    def run_language(self, lang, *, dark=False, full=False):
        from . import theme
        from .analysis_dialog import AnalysisDialog
        from .window import MainWindow

        self.language = lang
        tag = f"{lang}-{'dark' if dark else 'light'}"
        set_language(lang)
        theme.apply(self.app, dark=dark)
        self._pump(0.1)
        window = MainWindow()
        self.window = window
        window.project.dirty = False
        window.resize(1024, 768)
        window.show()
        self._pump(0.2)
        screen = window.screen().geometry() if window.screen() else None
        self.note(f"theme={'dark' if dark else 'light'}, dpr={window.devicePixelRatioF():.2f}, "
                  f"screen={screen}, size=1024x768")

        csv_path = self.folder / f"mood-{tag}.csv"
        csv_path.write_bytes(EXAMPLE.read_bytes())
        window.open_path(csv_path)
        self.wait(window)
        title = window.selected[1]

        def configure(dialog, *, fail_one=False):
            if dialog.method != mood.METHOD:
                dialog.method = mood.METHOD
                dialog.configure_fields()
            dialog.show()
            self._pump(0.1)
            _fill(dialog, columns=list("ABC"), ties=mood.BELOW, yates=False)
            if fail_one:
                _check_columns(dialog, ["A"])
                dialog.accept()
                self.expect(dialog.result is None and dialog.banner.isVisible(),
                            "one variable did not keep the dialog open")
                self.expect(dialog.error_field == mood.VARIABLES, f"focus field is {dialog.error_field}")
                self.shot(dialog, f"{tag}-dialog-error-1024x768")
                _fill(dialog, columns=list("ABC"), ties=mood.BELOW, yates=False)
            dialog.tabs.setCurrentIndex(1)
            self.shot(dialog, f"{tag}-dialog-1024x768")
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec",
                               lambda dialog: configure(dialog, fail_one=full)):
            window.analyze(mood.METHOD)
        self.wait(window)
        run = window.project.runs[0]
        self.expect(run.calculation_error is None, f"calculation error: {run.calculation_error}")
        if run.result is None:
            self.problems.append(f"[{lang}] no result")
            window.project.dirty = False
            window.close()
            return
        row = run.result.tables[mood.RESULT_SHEET].iloc[0]
        counts = run.result.tables[mood.COUNTS_SHEET]
        self.expect(float(row["Pooled median"]) == 3.0, f"pooled median is {row['Pooled median']}")
        self.expect(counts["Sample"].tolist() == ["A", "B", "C"], f"samples are {counts['Sample'].tolist()}")
        self.expect(counts["Tied"].tolist() == [2, 1, 1], f"tied counts are {counts['Tied'].tolist()}")
        self.note(f"chi-square {float(row['Chi-square']):.6g}, P {float(row['P']):.6g}")
        window.show_sheet("result", 0)
        self.shot(window, f"{tag}-result-1024x768")

        window.resize(1600, 1000)
        self._pump(0.15)

        def peek(dialog):
            dialog.show()
            self._pump(0.1)
            self.shot(dialog, f"{tag}-dialog-1600x1000")
            return QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", peek):
            window.change_parameters()
        self.shot(window, f"{tag}-result-1600x1000")

        if full:
            def change_ties(dialog):
                dialog.show()
                _fill(dialog, columns=list("ABC"), ties=mood.ABOVE, yates=False)
                dialog.accept()
                return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

            with mock.patch.object(AnalysisDialog, "exec", change_ties):
                window.change_parameters()
            self.wait(window)
            above_row = window.project.runs[0].result.tables[mood.RESULT_SHEET].iloc[0]
            self.expect(abs(float(above_row["P"]) - float(row["P"])) > 1e-12,
                        "Ties=Above did not change the p-value")
            self.note(f"after Ties=Above: P {float(above_row['P']):.6g}")

            def two_yates(dialog):
                dialog.show()
                _fill(dialog, columns=["A", "B"], ties=mood.BELOW, yates=True)
                self.expect(dialog.controls[mood.YATES][1].isEnabled(), "Yates disabled with two samples")
                dialog.accept()
                return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

            with mock.patch.object(AnalysisDialog, "exec", two_yates):
                window.change_parameters()
            self.wait(window)
            yates_settings = window.project.runs[0].result.tables[mood.SETTINGS_SHEET]["Value"]
            self.expect(bool(yates_settings["Yates applied"]), "Yates was not applied for two samples")

            window.show_sheet("data", title)
            edited = window.edit_cell(title, 0, 0, "10")
            self.expect(edited is not False, "the first A value was not edited")
            self.wait(window)
            updated = float(window.project.runs[0].result.tables[mood.RESULT_SHEET].iloc[0]["P"])
            self.note(f"after editing A row 1 to 10: P {updated:.6g}")

            window.show_sheet("result", 0)
            window.result_tabs.setCurrentIndex(
                list(window.project.runs[0].result.tables).index(mood.RESULT_SHEET))
            exported = self.folder / "mood-median.csv"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(exported), "CSV (*.csv)")):
                window.export()
            payload = exported.read_text(encoding="utf-8") if exported.exists() else ""
            self.expect("Pooled median" in payload and "Chi-square" in payload,
                        "the export is missing Pooled median or Chi-square")

            # No-inference path: Ignore empties both groups.
            ties = self.folder / "constant.csv"
            ties.write_text("A,B\n1,1\n1,1\n", encoding="utf-8")
            window.open_path(ties)
            self.wait(window)

            def accept_ignore(dialog):
                dialog.show()
                _fill(dialog, columns=["A", "B"], ties=mood.IGNORE, yates=False)
                dialog.accept()
                return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

            with mock.patch.object(AnalysisDialog, "exec", accept_ignore):
                window.analyze(mood.METHOD)
            self.wait(window)
            ties_run = window.project.runs[-1]
            self.expect(ties_run.calculation_error is None, f"ignore error: {ties_run.calculation_error}")
            ties_row = ties_run.result.tables[mood.RESULT_SHEET].iloc[0]
            self.expect(float(ties_row["Pooled median"]) == 1.0, "constant pooled median is not 1")
            self.expect(pd.isna(ties_row["P"]), "Ignore-empty still reported a p-value")
            self.note("Ignore on constant samples: inference empty, dialog accepted")
            self.shot(window, f"{tag}-ignore-result-1600x1000")

            project_path = self.folder / "mood-median.alab"
            window.project.save(project_path)
            saved = window.project.runs[0].result.tables[mood.RESULT_SHEET].copy()
            window.project.dirty = False
            window.close()
            self._pump(0.1)
            reopened = MainWindow()
            self.window = reopened
            reopened.resize(1600, 1000)
            reopened.show()
            reopened.open_path(project_path)
            self.wait(reopened)
            reopened.open_sheet(("result", 0))
            self.wait(reopened)
            self.shot(reopened, f"{tag}-reopened-1600x1000")
            reopened_run = reopened.project.runs[0]
            self.expect(reopened_run.calculation_error is None,
                        f"reopened calculation error: {reopened_run.calculation_error}")
            if reopened_run.result is None:
                self.expect(False, "reopened project has no result")
            else:
                try:
                    pd.testing.assert_frame_equal(
                        reopened_run.result.tables[mood.RESULT_SHEET], saved, check_dtype=False)
                    self.note(".alab reopened with the same Mood median sheet")
                except AssertionError as error:
                    self.expect(False, f".alab roundtrip mismatch: {error}")
            reopened.project.dirty = False
            reopened.close()
            self._pump(0.1)
            return

        window.project.dirty = False
        window.close()
        self._pump(0.1)

    def run(self):
        from . import theme
        preferences = self.folder / "preferences"
        preferences.mkdir(parents=True, exist_ok=True)
        old_xdg, old_appdata = os.environ.get("XDG_CONFIG_HOME"), os.environ.get("APPDATA")
        os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(preferences)
        try:
            self.app = QApplication.instance() or QApplication(["trama-mood-median-smoke"])
            theme.load_fonts()
            self.notes.append(
                f"env: platform={platform.platform()}, python={sys.version.split()[0]}, "
                f"PySide6={PYSIDE_VERSION}, numpy={np.__version__}, pandas={pd.__version__}, "
                f"scipy={scipy.__version__}, matplotlib={matplotlib.__version__}, "
                f"QPA={self.app.platformName()}, dpr="
                f"{(self.app.primaryScreen().devicePixelRatio() if self.app.primaryScreen() else 'n/a')}"
            )
            self.run_language("en", dark=False, full=True)
            self.run_language("it", dark=False, full=False)
            self.run_language("it", dark=True, full=False)
            self.run_language("en", dark=True, full=False)
        except Exception:
            self.problems.append(traceback.format_exc())
        finally:
            set_language("en")
            if old_xdg is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old_xdg
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
        status = "PASS" if not self.problems else "FAIL"
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        lines = [f"STATUS: {status}", "", "NOTES:", *self.notes]
        if self.problems:
            lines += ["", "PROBLEMS:", *self.problems]
        (self.folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0 if status == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    return MoodMedianSmoke(parser.parse_args(argv).folder).run()


if __name__ == "__main__":
    raise SystemExit(main())
