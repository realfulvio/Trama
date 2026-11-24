"""Desktop smoke for Power for paired proportions.

``python -m trama_qt --smoke FOLDER --only qt-mcnemar-power``

Empty project, English and Italian, light and dark, the window at 1024×768 and 1600×1000.
``app.py`` points preferences at ``FOLDER/preferences`` before importing this module, so the
run does not read or write the user's theme and language. Screenshots, a reopened ``.alab``,
the CSV and SVG exports and the 5,000-pair timing are written into FOLDER.
"""
import os
from pathlib import Path
import time
import tracemalloc
from unittest import mock

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel

from analisi import mcnemar_power as mp

SIZES = ((1024, 768), (1600, 1000))


def _expect(smoke, condition, text):
    if not condition:
        smoke.problem(text)
    return bool(condition)


def _labels(dialog):
    return [label.text() for label in dialog.findChildren(QLabel)]


def _timings(folder):
    """The load case is the sample-size search that walks every integer up to the declared limit."""
    fired = {}

    def cancel():
        if "armed" not in fired:
            fired["armed"] = time.perf_counter()
            return False
        if time.perf_counter() - fired["armed"] < 0.02:
            return False
        fired["at"] = time.perf_counter()
        return True

    try:
        mp.minimum_pairs(0.12, 0.10, 0.9, max_pairs=5000, cancel=cancel)
        latency = None
    except mp.McNemarPowerCancelled:
        latency = time.perf_counter() - fired["at"]
    tracemalloc.start()
    started = time.perf_counter()
    reached = mp.minimum_pairs(0.12, 0.10, 0.9, max_pairs=5000)
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    main_started = time.perf_counter()
    main = mp.minimum_pairs(0.3, 0.1, 0.8)
    main_elapsed = time.perf_counter() - main_started
    lines = [
        f"search to 5000 pairs (p01=0.12, p10=0.10, target=0.9): {elapsed:.3f} s, reached {reached}",
        f"cancel latency after the flag flipped: {None if latency is None else f'{latency:.4f} s'}",
        f"tracemalloc peak of the 5000-pair search: {peak / 2 ** 20:.2f} MiB",
        f"main case p01=0.30 p10=0.10 target=0.8: N={main} in {main_elapsed:.4f} s",
        f"power at N and at N-1: {mp.exact_power(main, 0.3, 0.1):.6f} {mp.exact_power(main - 1, 0.3, 0.1):.6f}",
    ]
    (Path(folder) / "mcnemar-power-timings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return reached is None and latency is not None and latency < 0.5 and elapsed < 15 and main == 84, lines


def _draw(smoke, widget):
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    for canvas in widget.findChildren(FigureCanvasQTAgg):
        if canvas.isVisible():
            canvas.draw()
    smoke.app.processEvents()


def _finish_dialog(dialog, accepted):
    if dialog.isVisible():
        dialog.close()
    if accepted and dialog.result is not None:
        return QDialog.DialogCode.Accepted
    return QDialog.DialogCode.Rejected


def _shot_dialog(smoke, window, script):
    from .analysis_dialog import AnalysisDialog
    seen = []

    def exec_(dialog):
        seen.append(dialog)
        dialog.show()
        smoke.app.processEvents()
        accepted = script(dialog)
        smoke.app.processEvents()
        return _finish_dialog(dialog, accepted)

    with mock.patch.object(AnalysisDialog, "exec", exec_):
        window.actions["paired_power"].trigger()
    return seen[0] if seen else None


def _run_case(smoke, window, language, mode, folder):
    from .theme import fit_dialog, keep_on_screen
    _expect(smoke, window.actions["paired_power"].isEnabled(), "paired power is disabled on an empty project")
    _expect(smoke, not window.project.tables, "the new window is not an empty project")
    for width, height in SIZES:
        window.resize(width, height)
        keep_on_screen(window)
        smoke.app.processEvents()
        smoke.shot(window, f"empty-{width}x{height}")

        def browse(dialog, width=width, height=height):
            fit_dialog(dialog, min(width - 16, 1280), min(height - 32, 900))
            smoke.shot(dialog, f"dialog-design-{width}x{height}")
            dialog.tabs.setCurrentIndex(1)
            smoke.app.processEvents()
            smoke.shot(dialog, f"dialog-effect-{width}x{height}")
            dialog.tabs.setCurrentIndex(2)
            smoke.app.processEvents()
            smoke.shot(dialog, f"dialog-curve-{width}x{height}")
            if width == 1024 and language == "it":
                dialog.tabs.setCurrentIndex(1)
                dialog.controls[mp.P01][1].setText("70,5")
                dialog.controls[mp.P10][1].setText("40")
                dialog.run_button.click()
                smoke.app.processEvents()
                smoke.shot(dialog, "dialog-bad-sum")
                _expect(smoke, dialog.error_field == mp.P10, f"bad sum focused {dialog.error_field}")
                _expect(smoke, "superano 100" in dialog.banner.text(), dialog.banner.text())
            return False

        _shot_dialog(smoke, window, browse)
        smoke.app.processEvents()

    def calculate(dialog):
        dialog.controls[mp.ALPHA][1].setText("5,0" if language == "it" else "5")
        dialog.controls[mp.TARGET][1].setText("0,8" if language == "it" else "0.8")
        dialog.controls[mp.P01][1].setText("30")
        dialog.controls[mp.P10][1].setText("10")
        dialog.controls[mp.GRAPH][1].setChecked(True)
        dialog.tabs.setCurrentIndex(0)
        smoke.shot(dialog, "dialog-ready")
        dialog.run_button.click()
        _expect(smoke, dialog.result is not None, dialog.banner.text())
        return dialog.result is not None

    window.resize(1600, 1000)
    keep_on_screen(window)
    _shot_dialog(smoke, window, calculate)
    smoke.wait()
    _expect(smoke, len(window.project.runs) == 1, f"{len(window.project.runs)} runs")
    if not window.project.runs:
        return
    run = window.project.runs[-1]
    report = run.result.tables[mp.METHOD]["Value"]
    _expect(smoke, report["N"] == 84, f"N is {report['N']}")
    _expect(smoke, report["Power"] >= 0.8, f"power is {report['Power']}")
    _expect(smoke, abs(report["Expected difference"] - 0.2) < 1e-12, report["Expected difference"])
    for width, height in SIZES:
        window.resize(width, height)
        keep_on_screen(window)
        window.open_sheet(("result", 0))
        smoke.wait()
        smoke.shot(window, f"result-{width}x{height}")
        window.open_sheet(("graph", 0))
        smoke.wait()
        _draw(smoke, window)
        smoke.shot(window, f"graph-{width}x{height}")

    if language != "it" or mode != "light":
        window.project.dirty = False
        return

    def swap(dialog):
        dialog.controls[mp.P01][1].setText("10")
        dialog.controls[mp.P10][1].setText("30")
        smoke.shot(dialog, "dialog-swapped")
        dialog.run_button.click()
        return dialog.result is not None

    window.open_sheet(("result", 0))
    smoke.wait()
    _shot_dialog_change(smoke, window, swap)
    smoke.wait()
    run = window.project.runs[-1]
    report = run.result.tables[mp.METHOD]["Value"]
    _expect(smoke, report["N"] == 84 and abs(report["Expected difference"] + 0.2) < 1e-12,
            f"swap N={report['N']} difference={report['Expected difference']}")
    path = Path(folder) / "paired-power.alab"
    window.project.save(path)
    _expect(smoke, window.close_project(), "close after save")
    window.open_path(path)
    smoke.wait()
    window.open_sheet(("result", 0))
    smoke.wait()
    reopened = window.project.runs[-1]
    _expect(smoke, reopened.options == run.options, "the reopened recipe changed")
    _expect(smoke, reopened.result.tables[mp.METHOD]["Value"]["N"] == 84, "reopened N")
    smoke.shot(window, "reopened-result")
    csv_path = Path(folder) / "paired-power.csv"
    svg_path = Path(folder) / "paired-power.svg"
    with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(csv_path), "CSV (*.csv)")):
        window.export()
    window.open_sheet(("graph", 0))
    smoke.wait()
    with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg_path), "SVG (*.svg)")):
        window.export()
    smoke.shot(window, "reopened-graph")
    _expect(smoke, csv_path.is_file() and b"84" in csv_path.read_bytes(), "CSV export")
    _expect(smoke, svg_path.is_file() and b"<svg" in svg_path.read_bytes(), "SVG export")
    window.project.dirty = False


def _shot_dialog_change(smoke, window, script):
    from .analysis_dialog import AnalysisDialog

    def exec_(dialog):
        dialog.show()
        smoke.app.processEvents()
        accepted = script(dialog)
        smoke.app.processEvents()
        return _finish_dialog(dialog, accepted)

    with mock.patch.object(AnalysisDialog, "exec", exec_):
        window.change_parameters()


def run(folder):
    """EN and IT, light and dark. Returns ``PASS`` or ``FAIL``."""
    import traceback as _traceback
    from analisi.i18n import active_language, set_language
    from . import theme
    from .smoke import Smoke
    from .window import MainWindow
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    smoke = Smoke(folder)
    smoke.app = QApplication.instance()
    previous_language, previous_mode = active_language(), theme.STATE["mode"]
    timing_ok, timing_lines = _timings(folder)
    if not timing_ok:
        smoke.problem("the 5000-pair timing was outside the declared budget: " + " | ".join(timing_lines))
    smoke.notes.extend(timing_lines)
    try:
        for language in ("en", "it"):
            for mode in ("light", "dark"):
                smoke.language = f"{language}-{mode}"
                set_language(language)
                theme.install_qt_translations(smoke.app, language)
                theme.set_mode(mode, smoke.app, remember=False)
                window = MainWindow()
                smoke.window = window
                window.error = lambda error, tag=smoke.language: smoke.problem(f"{tag}: error shown: {error}")
                window.resize(1600, 1000)
                window.show()
                theme.keep_on_screen(window)
                smoke.app.processEvents()
                try:
                    _run_case(smoke, window, language, mode, folder)
                except Exception:
                    smoke.problem("stopped:\n" + _traceback.format_exc())
                finally:
                    for session in window.sessions:
                        session.project.dirty = False
                    window.close()
                    window.deleteLater()
                    smoke.app.processEvents()
    finally:
        set_language(previous_language)
        theme.install_qt_translations(smoke.app, previous_language)
        theme.set_mode(previous_mode, smoke.app, remember=False)
    screen = smoke.app.primaryScreen()
    if screen is not None:
        smoke.notes.insert(0, f"platform {smoke.app.platformName()} · ratio {screen.devicePixelRatio()} · "
                               f"logical DPI {screen.logicalDotsPerInch()} · "
                               f"available {screen.availableGeometry().width()}×{screen.availableGeometry().height()}")
    return smoke.report()


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    folders = [argument for argument in argv if not argument.startswith("--")]
    if len(folders) != 1:
        print("Usage: python -m trama_qt.mcnemar_power_smoke FOLDER")
        return 2
    folder = Path(folders[0]).resolve()
    preferences = folder / "preferences"
    preferences.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = str(preferences)
    os.environ.setdefault("TRAMA_THEME", "light")
    os.environ.setdefault("MPLBACKEND", "QtAgg")
    from PySide6.QtCore import Qt as QtCore
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(QtCore.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Trama")
    app.setOrganizationName("TramaStat")
    from . import theme
    theme.load_fonts()
    theme.STATE["mode"] = theme.saved_mode()
    theme.apply(app)
    status = run(folder)
    print(f"McNemar power smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
