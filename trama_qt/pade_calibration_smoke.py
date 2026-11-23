"""Qt smoke verification for Padé (1,1) standard-curve calibration:
``python -m trama_qt.pade_calibration_smoke FOLDER [--dark]``.

Runs on the real Classica Qt window with temporary preferences (never touching
permanent user settings). Checks 1024x768 and 1600x1000 layouts, English and
Italian UI, light and dark themes, dialog validation/error banner, switching
from an interval-capable model back to None on Padé (1,1), both X-from-Y and
Y-from-X directions with out-of-range queries, live cell edit + recalculation,
CSV and vector SVG export, and saving/reopening a ``.alab`` project.

Writes all evidence into FOLDER (outside the repository): screenshots,
``pade-calibration.alab``, ``predictions.csv``, ``curve.svg``, ``report.txt``
and ``status.txt``. Exit code 0 on PASS, 1 on FAIL.
"""
import argparse
import os
from pathlib import Path
import platform
import sys
import tempfile
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

from analisi import nonlinear_calibration as cal  # noqa: E402
from analisi import pade_calibration as pade  # noqa: E402
from analisi.i18n import set_language  # noqa: E402

METHOD = "Interpolate a standard curve"
MODEL = pade.MODEL


def _synthetic_frame():
    xs = [10.0, 12.5, 15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 15.0, 22.5]
    zs = [(x - 10.0) / 20.0 for x in xs]
    ys = [(2.0 + 12.0 * z) / (1.0 + 2.0 * z) for z in zs]
    # Mild synthetic variation on replicates
    ys[9] += 0.03
    ys[10] -= 0.04
    return pd.DataFrame({
        "X": xs,
        "Y": ys,
        "X requests": [10.0, 17.5, 30.0, 5.0, 35.0] + [np.nan] * 6,
        "Y requests": [2.8, 3.7, 4.4, 1.0, 6.0] + [np.nan] * 6,
    })


def _fill(dialog, values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if hasattr(control, "findData"):
            idx = control.findData(value)
            assert idx >= 0, (name, value)
            control.setCurrentIndex(idx)
        else:
            control.setText(str(value))


class PadeSmoke:
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
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        for canvas in widget.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                canvas.draw()
        self._pump(0.2)
        target = self.folder / f"{name}.png"
        ok = widget.grab().save(str(target))
        self.expect(ok and target.exists() and target.stat().st_size > 0, f"failed to capture {target.name}")

    def check_dialog_geometry(self, dialog, label):
        self._pump(0.1)
        buttons = dialog.run_button
        rect = buttons.geometry()
        self.expect(rect.width() > 20 and rect.height() > 15, f"{label}: Run button collapsed ({rect})")
        self.expect(dialog.width() <= 1600 and dialog.height() <= 1000, f"{label}: dialog oversized")

    def run_language(self, lang, *, dark=False, sizes=((1024, 768), (1600, 1000)), export_artifacts=False):
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
        window.resize(*sizes[0])
        window.show()
        self._pump(0.2)

        dpr = window.devicePixelRatioF()
        screen = window.screen().geometry() if window.screen() else None
        self.note(f"theme={'dark' if dark else 'light'}, dpr={dpr:.2f}, screen={screen}, size={sizes[0]}")

        csv_in = self.folder / f"standards_{tag}.csv"
        _synthetic_frame().to_csv(csv_in, index=False)
        window.open_path(csv_in)
        self.wait(window)
        title = window.selected[1]

        # 1. Dialog check: interval switch -> Padé resets Uncertainty to None; error banner on invalid recipe.
        def script_inverse(dialog):
            if dialog.method != METHOD:
                dialog.method = METHOD
                dialog.configure_fields()
            dialog.show()
            self._pump(0.1)
            _fill(dialog, {
                "X": "X", "Y": "Y", cal.DIRECTION: "X from Y",
                cal.UNKNOWN_RESPONSES: "Y requests", "Curve": "Nonlinear",
                "Model": "One-phase decay", cal.UNCERTAINTY: "Prediction",
            })
            _fill(dialog, {"Model": MODEL})
            self.expect(dialog.controls[cal.UNCERTAINTY][1].currentData() == "None",
                        "switching to Padé did not reset Uncertainty to None")
            dialog.tabs.setCurrentIndex(1)
            self._pump(0.1)
            self.check_dialog_geometry(dialog, f"{tag}-dialog-options")
            self.shot(dialog, f"{tag}-dialog-options")

            # Trigger an error banner by selecting Y == X, capture it, then restore Y.
            _fill(dialog, {"Y": "X"})
            dialog.accept()
            self.expect(dialog.result is None and dialog.banner.isVisible(),
                        "error banner did not appear on X == Y")
            self.shot(dialog, f"{tag}-dialog-error")
            _fill(dialog, {"Y": "Y"})
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", script_inverse):
            window.analyze(METHOD)
        self.wait(window)
        inv_run = window.project.runs[0]
        self.expect(inv_run.calculation_error is None, f"inverse error: {inv_run.calculation_error}")
        inv_tbl = inv_run.result.tables[cal.INTERPOLATED]
        self.expect(inv_tbl["Status"].tolist() == [cal.IN_RANGE] * 3 + [cal.OUT_OF_RANGE] * 2,
                    f"unexpected inverse statuses: {inv_tbl['Status'].tolist()}")
        window.show_sheet("graph", 0)
        self.shot(window, f"{tag}-graph-inverse-{sizes[0][0]}x{sizes[0][1]}")

        # 2. Forward Y from X at the second window size (1600x1000).
        if len(sizes) > 1:
            window.resize(*sizes[1])
            self._pump(0.15)
        window.show_sheet("data", title)

        def script_forward(dialog):
            if dialog.method != METHOD:
                dialog.method = METHOD
                dialog.configure_fields()
            dialog.show()
            _fill(dialog, {
                "X": "X", "Y": "Y", cal.DIRECTION: "Y from X",
                cal.UNKNOWN_X: "X requests", "Curve": "Nonlinear", "Model": MODEL,
            })
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", script_forward):
            window.analyze(METHOD)
        self.wait(window)
        fwd_run = window.project.runs[1]
        self.expect(fwd_run.calculation_error is None, f"forward error: {fwd_run.calculation_error}")
        fwd_tbl = fwd_run.result.tables[cal.PREDICTIONS]
        self.expect(fwd_tbl["Status"].tolist() == [cal.IN_RANGE] * 3 + [cal.OUTSIDE_CALIBRATION] * 2,
                    f"unexpected forward statuses: {fwd_tbl['Status'].tolist()}")
        before_pred = float(fwd_tbl.at[1, "Predicted Y"])

        window.show_sheet("graph", 1)
        end_size = sizes[-1]
        self.shot(window, f"{tag}-graph-forward-{end_size[0]}x{end_size[1]}")

        # 3. Edit a measurement and verify automatic recalculation.
        window.show_sheet("data", title)
        window.edit_cell(title, 4, 1, "4.35")
        self.wait(window)
        after_pred = float(window.project.runs[1].result.tables[cal.PREDICTIONS].at[1, "Predicted Y"])
        self.expect(abs(after_pred - before_pred) > 1e-3,
                    f"recalculation did not update prediction ({before_pred} -> {after_pred})")
        self.note(f"recalc after cell edit: Predicted Y[1] {before_pred:.5f} -> {after_pred:.5f}")

        # 4. Exports (CSV, vector SVG) and .alab roundtrip.
        if export_artifacts:
            window.show_sheet("result", 1)
            window.result_tabs.setCurrentIndex(list(window.project.runs[1].result.tables).index(cal.PREDICTIONS))
            csv_out = self.folder / "predictions.csv"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(csv_out), "")):
                window.export()
            self.expect(csv_out.exists() and len(pd.read_csv(csv_out)) == 5, "CSV export failed")

            window.show_sheet("graph", 0)
            svg_out = self.folder / "curve.svg"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg_out), "")):
                window.export()
            svg_text = svg_out.read_text(encoding="utf-8") if svg_out.exists() else ""
            self.expect("<svg" in svg_text and "<path" in svg_text, "vector SVG export failed")

            alab_path = self.folder / "pade-calibration.alab"
            window.project.save(alab_path)
            self.expect(alab_path.exists() and alab_path.stat().st_size > 0, ".alab save failed")
            saved_fwd = window.project.runs[1].result.tables[cal.PREDICTIONS].copy()

            # Close and reopen .alab in a fresh MainWindow.
            window.project.dirty = False
            window.close()
            self._pump(0.15)

            reopened = MainWindow()
            self.window = reopened
            reopened.project.dirty = False
            reopened.resize(*sizes[0])
            reopened.show()
            reopened.open_path(alab_path)
            self.wait(reopened)
            reopened.open_sheet(("graph", 1))
            self.wait(reopened)
            got_fwd = reopened.project.runs[1].result.tables[cal.PREDICTIONS]
            try:
                pd.testing.assert_frame_equal(got_fwd, saved_fwd)
                self.note(".alab reopened and recalculated identically")
            except AssertionError as err:
                self.expect(False, f".alab roundtrip mismatch: {err}")
            reopened.project.dirty = False
            reopened.close()
            self._pump(0.1)
        else:
            window.project.dirty = False
            window.close()
            self._pump(0.1)

    def run(self):
        from . import theme
        with tempfile.TemporaryDirectory() as pref_dir:
            old_xdg = os.environ.get("XDG_CONFIG_HOME")
            old_appdata = os.environ.get("APPDATA")
            os.environ["XDG_CONFIG_HOME"] = pref_dir
            os.environ["APPDATA"] = pref_dir
            try:
                self.app = QApplication.instance() or QApplication(["trama-pade-smoke"])
                theme.load_fonts()
                self.notes.append(
                    f"env: platform={platform.platform()}, python={sys.version.split()[0]}, "
                    f"PySide6={PYSIDE_VERSION}, numpy={np.__version__}, pandas={pd.__version__}, "
                    f"scipy={scipy.__version__}, matplotlib={matplotlib.__version__}, "
                    f"QPA={self.app.platformName()}"
                )
                self.run_language("en", dark=False, sizes=((1024, 768), (1600, 1000)), export_artifacts=True)
                self.run_language("it", dark=False, sizes=((1024, 768), (1600, 1000)), export_artifacts=False)
                # Always include at least one dark-theme check (IT at 1024x768 and 1600x1000).
                self.run_language("it", dark=True, sizes=((1024, 768), (1600, 1000)), export_artifacts=False)
                if self.dark:
                    self.run_language("en", dark=True, sizes=((1024, 768),), export_artifacts=False)
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
        return 0 if status == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qt smoke check for Padé (1,1) calibration.")
    parser.add_argument("folder", type=Path, help="Output folder for evidence (outside the repo).")
    parser.add_argument("--dark", action="store_true", help="Also run an English dark-theme pass.")
    args = parser.parse_args(argv)
    return PadeSmoke(args.folder, dark=args.dark).run()


if __name__ == "__main__":
    raise SystemExit(main())
