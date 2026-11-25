"""Qt desktop smoke for Mann–Whitney and Wilcoxon rank/paired-difference graphs.

``python -m trama_qt.rank_graphs_smoke FOLDER`` or
``python -m trama_qt --smoke FOLDER --only qt-rank-graphs``.

Runs on a real ``MainWindow`` with isolated preferences across EN/IT, light/dark themes,
``1024x768`` and ``1600x1000``, legacy recipe preservation with ``#infoBanner``, pending
navigator/Gallery entries after reopening ``.alab``, cell edit + recalculation, and PNG/SVG/PDF export.
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
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QTreeWidgetItemIterator  # noqa: E402

from analisi.data import Dataset, save_project  # noqa: E402
from analisi.i18n import set_language  # noqa: E402
from analisi.rank_graphs import LEGACY_P_METHOD, RANK_PLOT, WILCOXON_DIFFERENCES  # noqa: E402
from analisi.rank_tests import (  # noqa: E402
    ALTERNATIVE,
    AUTOMATIC,
    CONTINUITY,
    MANN_WHITNEY,
    PRATT,
    P_VALUE,
    WILCOXON,
    ZERO_DIFFERENCES,
)
from trama_qt.analysis_dialog import AnalysisDialog  # noqa: E402
from trama_qt.gallery_catalog import catalog  # noqa: E402
from trama_qt.window import MainWindow, export_graph  # noqa: E402


def _navigator_refs(window):
    refs = set()
    items = QTreeWidgetItemIterator(window.navigator)
    while (item := items.value()) is not None:
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if ref:
            refs.add(tuple(ref))
        items += 1
    return refs


class RankGraphsSmoke:
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

    def wait(self, window=None, timeout=45.0):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.expect(window.job is None, "calculation did not finish in time")

    def shot(self, widget, name):
        self._pump(0.18)
        target = self.folder / f"{name}.png"
        ok = widget.grab().save(str(target))
        self.expect(ok and target.exists() and target.stat().st_size > 0, f"failed to capture {target.name}")

    def _apply_mode(self, lang, dark):
        from . import theme

        self.language = lang
        set_language(lang)
        theme.install_qt_translations(self.app, lang)
        theme.STATE["mode"] = "dark" if dark else "light"
        theme.apply(self.app)

    def _build_fixture_project(self, target_path):
        mw_ds = Dataset(
            pd.DataFrame({
                "Response $": [3.0, 7.0, 3.0, 5.0, 8.0],
                "Group $": ["Dose $", "Dose $", "B", "B", "B"],
            }),
            analyses=[(
                MANN_WHITNEY,
                {
                    "Response": "Response $",
                    "Group": "Group $",
                    P_VALUE: AUTOMATIC,
                    ALTERNATIVE: "Two-sided",
                    CONTINUITY: True,
                    RANK_PLOT: True,
                },
            )],
        )
        wx_ds = Dataset(
            pd.DataFrame({
                "First": [5.0, 1.0, 2.0, 8.0, np.nan],
                "Second": [1.0, 5.0, 2.0, 1.0, 9.0],
            }),
            analyses=[(
                WILCOXON,
                {
                    "First": "First",
                    "Second": "Second",
                    P_VALUE: AUTOMATIC,
                    ALTERNATIVE: "Two-sided",
                    CONTINUITY: True,
                    ZERO_DIFFERENCES: PRATT,
                    RANK_PLOT: True,
                    WILCOXON_DIFFERENCES: True,
                },
            )],
        )
        legacy_ds = Dataset(
            pd.DataFrame({"Response": [3.0, 7.0, 3.0, 5.0, 8.0], "Group": ["Dose $", "Dose $", "B", "B", "B"]}),
            analyses=[(MANN_WHITNEY, {"Response": "Response", "Group": "Group"})],
        )
        save_project(target_path, {"MW Dose": mw_ds, "Wilcoxon Pratt": wx_ds, "MW Legacy": legacy_ds})

    def run_pass(self, lang, *, dark, width, height, full=False):
        tag = f"{lang}-{'dark' if dark else 'light'}-{width}x{height}"
        self._apply_mode(lang, dark)
        project_path = self.folder / "rank-graphs-collaudo.alab"
        if not project_path.exists():
            self._build_fixture_project(project_path)

        window = MainWindow()
        self.window = window
        window.resize(width, height)
        window.show()
        window.open_path(project_path)
        self._pump(0.15)

        try:
            # Verify pending rank graph entries exist immediately after opening .alab (before compute).
            if full:
                nav_refs = _navigator_refs(window)
                gal_refs = {entry.ref for entry in catalog(window.project)}
                self.expect(("graph", 0) in nav_refs and ("graph", 1) in nav_refs,
                            "pending rank graphs missing from navigator")
                self.expect(("graph", 0) in gal_refs and ("graph", 1) in gal_refs,
                            "pending rank graphs missing from Gallery")
                self.note("verified pending graph entries in Navigator and Gallery upon .alab open")

            # Open Mann-Whitney graph (Dose $)
            window.open_sheet(("graph", 0))
            self.wait(window)
            mw_run = window.project.runs[0]
            self.expect(mw_run.calculation_error is None, f"MW error: {mw_run.calculation_error}")
            self.expect(mw_run.result is not None and mw_run.result.figure is not None, "MW figure missing")
            if mw_run.result is not None and mw_run.result.figure is not None:
                self.shot(window, f"{tag}-mw-graph")
                if full:
                    for fmt in ("png", "svg", "pdf"):
                        out = self.folder / f"{tag}-mw.{fmt}"
                        export_graph(mw_run.result.figure, out)
                        self.expect(out.exists() and out.stat().st_size > 400, f"failed MW export {fmt}")

            # Open Wilcoxon two-panel graph (Pratt + Paired differences)
            window.open_sheet(("graph", 1))
            self.wait(window)
            wx_run = window.project.runs[1]
            self.expect(wx_run.calculation_error is None, f"Wilcoxon error: {wx_run.calculation_error}")
            self.expect(wx_run.result is not None and wx_run.result.figure is not None
                        and len(wx_run.result.figure.axes) == 2,
                        "Wilcoxon combined 2-panel figure missing")
            if wx_run.result is not None and wx_run.result.figure is not None:
                self.shot(window, f"{tag}-wilcoxon-2panel")
                if full:
                    for fmt in ("png", "svg", "pdf"):
                        out = self.folder / f"{tag}-wilcoxon.{fmt}"
                        export_graph(wx_run.result.figure, out)
                        self.expect(out.exists() and out.stat().st_size > 400, f"failed Wilcoxon export {fmt}")

            if full:
                # Inspect AnalysisDialog Options tab for Wilcoxon (defaults off, then capture)
                def peek_wilcoxon(dialog):
                    dialog.show()
                    dialog.focus_field(RANK_PLOT)
                    self._pump(0.15)
                    self.shot(dialog, f"{tag}-wilcoxon-dialog")
                    return QDialog.DialogCode.Rejected

                with mock.patch.object(AnalysisDialog, "exec", peek_wilcoxon):
                    window.open_sheet(("result", 1))
                    window.change_parameters()

                # Verify Legacy recipe dialog shows Legacy choice + infoBanner and enables Plot ranks without migrating
                window.open_sheet(("result", 2))
                self.wait(window)

                def enable_legacy_plot(dialog):
                    dialog.show()
                    dialog.focus_field(RANK_PLOT)
                    self.expect(dialog.controls[P_VALUE][1].currentData() == LEGACY_P_METHOD,
                                "legacy dialog did not select Legacy p-value")
                    self._pump(0.15)
                    self.shot(dialog, f"{tag}-legacy-dialog")
                    dialog.controls[RANK_PLOT][1].setChecked(True)
                    dialog.accept()
                    return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

                with mock.patch.object(AnalysisDialog, "exec", enable_legacy_plot):
                    window.change_parameters()
                self.wait(window)
                legacy_run = window.project.runs[2]
                self.expect(P_VALUE not in legacy_run.options, "legacy recipe unexpectedly migrated")
                self.expect(list(legacy_run.result.tables.keys()) == [MANN_WHITNEY],
                            "legacy table set changed after enabling rank plot")
                self.expect(legacy_run.result.figure is not None, "legacy rank plot not rendered")

                # Open Gallery and capture preview cards
                window.open_gallery()
                self._pump(0.6)
                self.shot(window, f"{tag}-gallery")
                window.close_gallery()

                # Cell edit & recalculation updates Ranks and Wilcoxon graph
                affected = window.project.paste("Wilcoxon Pratt", 0, 0, [["10"]], "Edit cell")
                window.refresh_runs(affected)
                self.wait(window)
                new_diffs = window.project.runs[1].result.tables["Ranks"]["Difference"].tolist()
                self.expect(new_diffs == [9.0, -4.0, 0.0, 7.0], f"unexpected diffs after edit: {new_diffs}")
                self.note("cell edit updated Wilcoxon Ranks table and figure cleanly")

            elif dark:
                # Capture dark Gallery too
                window.open_gallery()
                self._pump(0.6)
                self.shot(window, f"{tag}-gallery")
                window.close_gallery()
        finally:
            window.project.dirty = False
            window.close()
            self._pump(0.1)

    def run(self):
        from . import theme

        preferences = self.folder / "preferences"
        preferences.mkdir(parents=True, exist_ok=True)
        old_xdg = os.environ.get("XDG_CONFIG_HOME")
        old_appdata = os.environ.get("APPDATA")
        os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(preferences)
        try:
            self.app = QApplication.instance() or QApplication(["trama-rank-graphs-smoke"])
            theme.load_fonts()
            screen = self.app.primaryScreen()
            self.notes.append(
                f"env: platform={platform.platform()}, python={sys.version.split()[0]}, "
                f"PySide6={PYSIDE_VERSION}, numpy={np.__version__}, pandas={pd.__version__}, "
                f"matplotlib={matplotlib.__version__}, QPA={self.app.platformName()}, "
                f"dpr={(screen.devicePixelRatio() if screen else 'n/a')}"
            )
            self.run_pass("en", dark=False, width=1024, height=768, full=True)
            self.run_pass("it", dark=False, width=1600, height=1000, full=False)
            self.run_pass("it", dark=True, width=1024, height=768, full=False)
        except Exception:
            self.problems.append(traceback.format_exc())
        finally:
            set_language("en")
            for key, value in (("XDG_CONFIG_HOME", old_xdg), ("APPDATA", old_appdata)):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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
    return RankGraphsSmoke(parser.parse_args(argv).folder).run()


if __name__ == "__main__":
    raise SystemExit(main())
