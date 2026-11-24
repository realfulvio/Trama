"""Qt smoke for Yuen's trimmed-mean test.

``python -m trama_qt.yuen_smoke FOLDER`` or
``python -m trama_qt --smoke FOLDER --only qt-yuen-trimmed-means``.

Real window, isolated preferences. English light drives the field error, the Italian comma is covered
by the Italian passes, both window sizes, one dark pass, a column swap, a cell edit, CSV export and
a reopened ``.alab``. Evidence stays in FOLDER.
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
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog  # noqa: E402

from analisi import yuen  # noqa: E402
from analisi.i18n import set_language  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent / "tests" / "data" / "yuen" / "columns.csv"


def _fill(dialog, values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if hasattr(control, "findData"):
            index = control.findData(value)
            assert index >= 0, (name, value)
            control.setCurrentIndex(index)
        else:
            control.setText(str(value))


class YuenSmoke:
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

    def time_large(self):
        generator = np.random.default_rng(0)
        first = generator.normal(size=50_000)
        second = generator.normal(size=50_000) + 0.2
        started = time.perf_counter()
        summary = yuen.yuen_summary(first, second, trim=0.2, level=0.95)
        elapsed = time.perf_counter() - started
        self.notes.append(
            f"50000+50000 trim 20%: {elapsed:.3f}s, effective N {summary['h_a']}+{summary['h_b']}, "
            f"difference {summary['difference']:.6g}"
        )

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

        csv_path = self.folder / f"columns-{tag}.csv"
        csv_path.write_bytes(EXAMPLE.read_bytes())
        window.open_path(csv_path)
        self.wait(window)
        title = window.selected[1]

        def configure(dialog, *, fail_level=False, italian_trim=False):
            if dialog.method != yuen.METHOD:
                dialog.method = yuen.METHOD
                dialog.configure_fields()
            dialog.show()
            self._pump(0.1)
            _fill(dialog, {yuen.FIRST: "Control", yuen.SECOND: "Treated", yuen.INPUT: yuen.COLUMNS})
            if italian_trim:
                dialog.controls[yuen.TRIM][1].setText("20,5")
            if fail_level:
                dialog.controls[yuen.LEVEL][1].setText("101")
                dialog.accept()
                self.expect(dialog.result is None and dialog.banner.isVisible(), "level 101 did not keep the dialog open")
                self.expect(dialog.error_field == yuen.LEVEL, f"focus field is {dialog.error_field}")
                self.expect(dialog.controls[yuen.FIRST][1].currentData() == "Control", "the first column was cleared")
                self.shot(dialog, f"{tag}-dialog-error-1024x768")
                dialog.controls[yuen.LEVEL][1].setText("95")
            dialog.tabs.setCurrentIndex(1)
            self.shot(dialog, f"{tag}-dialog-1024x768")
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec",
                               lambda dialog: configure(dialog, fail_level=full, italian_trim=lang == "it")):
            window.analyze(yuen.METHOD)
        self.wait(window)
        run = window.project.runs[0]
        self.expect(run.calculation_error is None, f"calculation error: {run.calculation_error}")
        if run.result is None:
            self.problems.append(f"[{lang}] no result")
            window.project.dirty = False
            window.close()
            return
        sheet = run.result.tables[yuen.EFFECT_SHEET]["Value"]
        removed = int(run.result.tables[yuen.GROUPS_SHEET].set_index("Role").loc["First", "Removed per tail"])
        self.expect(removed == 1, f"removed per tail is {removed}")
        if lang == "it":
            self.expect(run.options.get(yuen.TRIM) == 20.5, f"Italian trim was stored as {run.options.get(yuen.TRIM)}")
        difference = float(sheet["Difference"])
        self.note(f"difference {difference:.6g}, inference {sheet['Inference']}")
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
            def swap(dialog):
                dialog.show()
                _fill(dialog, {yuen.FIRST: "Treated", yuen.SECOND: "Control"})
                dialog.accept()
                return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

            with mock.patch.object(AnalysisDialog, "exec", swap):
                window.change_parameters()
            self.wait(window)
            swapped = float(window.project.runs[0].result.tables[yuen.EFFECT_SHEET]["Value"]["Difference"])
            self.expect(abs(swapped + difference) < 1e-9, f"swap did not reverse the difference ({difference} -> {swapped})")
            self.note(f"after swapping columns: {swapped:.6g}")

            window.show_sheet("data", title)
            edited = window.edit_cell(title, 2, 0, "30")
            self.expect(edited is not False, "the central Control value was not edited")
            self.wait(window)
            updated = float(window.project.runs[0].result.tables[yuen.EFFECT_SHEET]["Value"]["Difference"])
            self.expect(abs(updated - swapped) > 1e-6, f"edit did not recalculate ({swapped} -> {updated})")
            self.note(f"after editing Control row 3 to 30: {updated:.6g}")

            window.show_sheet("result", 0)
            window.result_tabs.setCurrentIndex(list(window.project.runs[0].result.tables).index(yuen.EFFECT_SHEET))
            exported = self.folder / "yuen-effect.csv"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(exported), "CSV (*.csv)")):
                window.export()
            payload = exported.read_text(encoding="utf-8") if exported.exists() else ""
            self.expect("Difference" in payload and "CI low" in payload and "CI high" in payload,
                        "the effect export is missing the estimate or the interval")

            project_path = self.folder / "yuen-trimmed-means.alab"
            window.project.save(project_path)
            saved = window.project.runs[0].result.tables[yuen.EFFECT_SHEET]["Value"].copy()
            window.project.dirty = False
            window.close()
            self._pump(0.1)
            reopened = MainWindow()
            self.window = reopened
            reopened.resize(1600, 1000)
            reopened.show()
            reopened.open_path(project_path)
            self.wait(reopened)
            # Opening the result starts the recalculation; show_sheet alone leaves it uncalculated.
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
                    pd.testing.assert_series_equal(
                        reopened_run.result.tables[yuen.EFFECT_SHEET]["Value"], saved, check_names=False)
                    self.note(".alab reopened with the same effect sheet")
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
            self.app = QApplication.instance() or QApplication(["trama-yuen-smoke"])
            theme.load_fonts()
            self.time_large()
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
    return YuenSmoke(parser.parse_args(argv).folder).run()


if __name__ == "__main__":
    raise SystemExit(main())
