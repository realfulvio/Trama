"""Desktop acceptance smoke for multivariate Bubble plots in Classica Qt.

    python -m trama_qt.bubble_multivariate_smoke OUT [--lang en|it] [--theme light|dark]
"""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "data" / "bubble_multivariate" / "misure-multivariato.alab"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="it")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-bubble-smoke-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    import pandas as pd
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from analisi.bubble import ATTR, COLOR_LIMITS, COLOR_MAX, COLOR_MIN, FILL_CONTINUOUS, FILL_MODE, SIZE_FIXED, SIZE_MODE
    from analisi.figure_export import export_figure
    from analisi.i18n import set_language
    from analisi.presentation import compose_layout

    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-bubble-multivariate-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.analysis_dialog import AnalysisDialog
    from trama_qt.bubble_style import BubbleStyleDialog
    from trama_qt.shortcuts_dialog import ShortcutsDialog
    from trama_qt.window import MainWindow

    problems, shots = [], []
    tag = f"{args.lang}-{args.theme}"

    def check(cond, text):
        if not cond:
            problems.append(text)

    def settle(steps=6):
        for _ in range(steps):
            app.processEvents()
            time.sleep(0.02)

    def capture(widget, name):
        settle()
        path = out / f"{tag}-{name}.png"
        widget.grab().save(str(path))
        shots.append(str(path))

    win = MainWindow()
    win.error = lambda err: problems.append(f"window error: {err}")
    win._ask = lambda *a, error=None, **k: problems.append(f"calculation error: {error}")
    def wait_job():
        deadline = time.monotonic() + 45.0
        while win.job is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    try:
        available = (win.screen() or app.primaryScreen()).availableGeometry()
        win.resize(min(1024, available.width()), min(768, available.height()))
        win.show()
        settle()

        work_alab = out / f"{tag}-work.alab"
        shutil.copy2(FIXTURE, work_alab)
        win.open_path(str(work_alab))
        wait_job()
        win.open_sheet(("graph", 0))
        wait_job()
        check(bool(win.project.runs) and win.project.runs[0].result is not None, "fixture failed to compute")

        # Verify narrow 1024x768 layout + contextual action + Inspector open
        check(win.actions["bubble_style"].isEnabled(), "bubble_style action not enabled")
        check(win.actions["bubble_style"].shortcut() == QKeySequence("Ctrl+Shift+B"), "missing Ctrl+Shift+B")

        win.toggle_inspector()
        settle()
        check(win.inspector is not None and win.inspector.bubble_section is not None, "inspector missing bubble_section")
        capture(win, "1024-inspector")

        # Wide layout (capped to active virtual screen size at current DPR)
        wide_avail = (win.screen() or app.primaryScreen()).availableGeometry()
        win.resize(min(1360, wide_avail.width()), min(860, wide_avail.height()))
        settle()
        capture(win, "wide-inspector")

        # Keyboard Tab navigation + F1 shortcut dialog check
        win.inspector.bubble_section.palette.setFocus()
        QTest.keyClick(win.inspector.bubble_section.palette, Qt.Key.Key_Tab)
        settle()
        def drive_shortcuts():
            dlg = app.activeModalWidget()
            if isinstance(dlg, ShortcutsDialog):
                capture(dlg, "shortcuts-f1")
                dlg.reject()
        QTimer.singleShot(120, drive_shortcuts)
        win.show_shortcuts()
        settle()

        # Zero recalculation during preview, Esc cancel, Apply, and Undo/Redo
        run = win.project.runs[0]
        with patch("trama_qt.project.compute", side_effect=AssertionError("Recalculation forbidden!")):
            def drive_cancel():
                dlg = app.activeModalWidget()
                if isinstance(dlg, BubbleStyleDialog):
                    dlg.tabs.setCurrentIndex(1)
                    dlg.palette.set_value("Blue–red")
                    dlg.preview()
                    capture(dlg, "dialog-preview")
                    QTest.keyClick(dlg, Qt.Key.Key_Escape)

            QTimer.singleShot(150, drive_cancel)
            win.edit_bubble_style()
            settle()
            check(getattr(run.result.figure, ATTR)["effective_encoding"]["palette"] == "Viridis",
                  "Esc did not revert BubbleStyleDialog preview")

            def drive_apply():
                dlg = app.activeModalWidget()
                if isinstance(dlg, BubbleStyleDialog):
                    dlg.tabs.setCurrentIndex(1)
                    dlg.palette.set_value("Blue–red")
                    dlg.limits_mode.setCurrentIndex(dlg.limits_mode.findData("Manual"))
                    dlg.color_min.setText("0")
                    dlg.color_mid.setText("25")
                    dlg.color_max.setText("100")
                    dlg.tabs.setCurrentIndex(2)
                    dlg.level_symbols._combos[0][1].set_value("*")
                    dlg.preview()
                    capture(dlg, "dialog-symbols")
                    dlg.accept()

            QTimer.singleShot(150, drive_apply)
            win.edit_bubble_style()
            settle()
            check(getattr(run.result.figure, ATTR)["effective_encoding"]["palette"] == "Blue–red", "Apply failed")
            check(getattr(run.result.figure, ATTR)["rendered_points"]["markers"][0] == "*", "Symbol override failed")

            # Undo / Redo single step
            win.undo()
            settle()
            check(getattr(run.result.figure, ATTR)["effective_encoding"]["palette"] == "Viridis", "Undo failed")
            win.undo(redo=True)
            settle()
            check(getattr(run.result.figure, ATTR)["effective_encoding"]["palette"] == "Blue–red", "Redo failed")

        # Export PNG, SVG, PDF and multi-panel Layout PDF/SVG
        for ext in ("png", "svg", "pdf"):
            exp = out / f"{tag}-figure.{ext}"
            export_figure(run.result.figure, exp, {"format": ext, "dpi": 150})
            check(exp.exists() and exp.stat().st_size > 400, f"export {ext} failed")
        layout = compose_layout("Bubble smoke layout", 1, [run.result.figure])
        l_pdf = out / f"{tag}-layout.pdf"
        l_svg = out / f"{tag}-layout.svg"
        export_figure(layout, l_pdf, {"format": "pdf"})
        export_figure(layout, l_svg, {"format": "svg"})
        check(l_pdf.exists() and l_pdf.stat().st_size > 500, "layout pdf failed")
        check(l_svg.exists() and l_svg.stat().st_size > 500, "layout svg failed")

        # Verify AnalysisDialog Fixed area + Error focusing cleanly
        df = win.project.tables["Misure"].raw
        adlg = AnalysisDialog(win, df, only="Bubble plot")
        adlg.show()
        adlg.controls[SIZE_MODE][1].setCurrentIndex(adlg.controls[SIZE_MODE][1].findData(SIZE_FIXED))
        adlg.controls[FILL_MODE][1].setCurrentIndex(adlg.controls[FILL_MODE][1].findData(FILL_CONTINUOUS))
        adlg.controls[COLOR_LIMITS][1].setCurrentIndex(adlg.controls[COLOR_LIMITS][1].findData("Manual"))
        adlg.controls[COLOR_MIN][1].setText("99")
        adlg.controls[COLOR_MAX][1].setText("10")
        settle()
        capture(adlg, "analysis-dialog")
        adlg.reject()
        adlg.deleteLater()

        capture(win, "final-graph")
    except Exception:
        problems.append(traceback.format_exc())
    finally:
        win.project.dirty = False
        win.close()
        app.processEvents()
        shutil.rmtree(prefs, ignore_errors=True)

    summary = {
        "lang": args.lang,
        "theme": args.theme,
        "qpa": app.platformName(),
        "dpr": app.devicePixelRatio(),
        "pyside": pyside,
        "shots": shots,
        "problems": problems,
    }
    print(summary)
    if problems:
        raise SystemExit("\n".join(problems))


if __name__ == "__main__":
    main()
