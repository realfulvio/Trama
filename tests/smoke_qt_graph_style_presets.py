"""Desktop acceptance of Graph → Figure styles… on the real screen, with screenshots.

    python tests/smoke_qt_graph_style_presets.py OUT [--lang en|it] [--theme light|dark]

Uses a temporary preferences folder (the user's library is never read or written) and the synthetic session
in ``tests/data/graph_style_presets``. It saves «Pubblicazione» from the first graph, previews it on the
second graph and cancels, applies it, saves and reopens the project, applies the imported style in a second
project and exports SVG/PDF. Every step is checked; ``OUT`` receives PNG screenshots of the window and the
dialog, the exports, ``report.txt`` (platform, screen, scale, problems) and ``status.txt`` (PASS or FAIL).
The calculation engine is counted during preview and Apply and must not run.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "graph_style_presets"
PUBLICATION = {"accent": "#0B7A73", "font_family": "serif", "title_size": 18, "grid": True, "legend": "upper right"}
SHAPE = {"id": "0b7a7300-0000-4000-8000-000000000003", "kind": "rectangle", "units": "axes",
         "points": [[0.08, 0.62], [0.32, 0.86]], "stroke": "#AA4433", "width": 1.5, "line_style": "dashed",
         "fill": None, "alpha": 1.0, "layer": "above"}
SECOND = {"title": "Calibrazione B", "xlabel": "Tempo", "accent": "#AA4433", "grid": False, "xscale": "log",
          "shapes": [SHAPE]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-style-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    from PySide6 import __version__ as pyside
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from matplotlib.colors import to_hex

    from analisi.i18n import set_language
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-style-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app, dark=args.theme == "dark")
    theme.install_qt_translations(app, args.lang)
    import trama_qt.project as project_module
    import trama_qt.window as window_module
    from trama_qt import graph_style_presets as gsp
    from trama_qt.graph_style_preset_dialog import GraphStylePresetDialog
    from trama_qt.window import MainWindow, export_graph

    problems, shots = [], []
    tag = f"{args.lang}-{args.theme}"

    def check(condition, text):
        if not condition:
            problems.append(text)

    def settle():
        for _ in range(5):
            app.processEvents()
            time.sleep(0.02)

    def shot(widget, name):
        settle()
        frame, available = widget.frameGeometry(), (widget.screen() or app.primaryScreen()).availableGeometry()
        check(frame.width() <= available.width() and frame.height() <= available.height(),
              f"{name}: {frame.width()}×{frame.height()} does not fit {available.width()}×{available.height()}")
        path = out / f"{tag}-{len(shots) + 1:02d}-{name}.png"
        check(widget.grab().save(str(path)), f"{name}: screenshot not written")
        shots.append(path.name)

    window = MainWindow()
    errors = []
    window.error = lambda error: errors.append(str(error))
    window._ask = lambda *a, error=None, **k: errors.append(f"calculation failed: {error}")
    available = (window.screen() or app.primaryScreen()).availableGeometry()
    window.resize(min(1280, available.width()), min(800, available.height()))
    window.show()
    theme.keep_on_screen(window)

    def wait():
        end = time.monotonic() + 120
        while window.job is not None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    def open_session(path):
        window.open_path(path)
        settle()
        for index in range(len(window.project.runs)):
            window.open_sheet(("graph", index))
            wait()

    def commit(index, style):
        from analisi.presentation import apply_style
        run = window.project.runs[index]
        window.open_sheet(("graph", index))
        wait()
        apply_style(run.result.figure, style)
        window.commit_style(run, deepcopy(style))
        window.show_sheet("graph", index)
        return run

    def with_dialog(steps):
        """Run the command; ``steps(dialog)`` plays the user on the real, visible dialog."""
        original = GraphStylePresetDialog.exec

        def run(dialog):
            dialog.show()
            settle()
            steps(dialog)
            settle()
            return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected

        GraphStylePresetDialog.exec = run
        try:
            window.graph_style_presets()
        finally:
            GraphStylePresetDialog.exec = original

    def choose(dialog, name):
        items = dialog.list.findItems(name, Qt.MatchFlag.MatchExactly)
        check(bool(items), f"style {name} not listed")
        if items:
            dialog.list.setCurrentItem(items[0])

    calls = []
    try:
        work = Path(tempfile.mkdtemp(prefix="trama-style-work-"))
        session = work / "sessione.alab"
        session.write_bytes((DATA / "sessione.alab").read_bytes())
        open_session(session)
        first, second = commit(0, PUBLICATION), commit(1, SECOND)
        window.ribbon_tabs.setCurrentIndex(window.ribbon_pages["graph"])
        window.open_sheet(("graph", 0))
        shot(window, "ribbon-graph")
        check(window.actions["graph_style_presets"].isEnabled(), "Figure styles… disabled on a graph")

        def save(dialog):
            dialog.name.setText(" Pubblicazione ")
            dialog.name.setFocus()
            from PySide6.QtTest import QTest
            QTest.keyClick(dialog.name, Qt.Key.Key_Return)
            check(dialog.isVisible(), "Enter in the name field closed the dialog")
            shot(dialog, "dialog-saved")
            dialog.reject()

        with_dialog(save)
        stored = json.loads(gsp.library_path().read_text(encoding="utf-8"))
        check(stored["presets"] == [{"version": 1, "name": "Pubblicazione", "style": PUBLICATION}],
              f"library content {stored}")

        for name in ("compute", "xy_series", "analyse"):
            for module in (project_module, window_module):
                if hasattr(module, name):
                    original = getattr(module, name)
                    setattr(module, name, lambda *a, _n=name, **k: calls.append(_n))
                    setattr(module, "_smoke_" + name, original)
        window.open_sheet(("graph", 1))
        axes = second.result.figure.axes[0]
        confirmed = to_hex(axes.lines[0].get_color())
        shot(window, "second-before")

        def preview_cancel(dialog):
            choose(dialog, "Pubblicazione")
            check(to_hex(axes.lines[0].get_color()) == "#0b7a73", "preview did not recolour the graph")
            check(axes.xaxis.get_gridlines()[0].get_visible(), "preview did not show the grid")
            shot(window, "second-preview")
            shot(dialog, "dialog-preview")
            from PySide6.QtTest import QTest
            QTest.keyClick(dialog, Qt.Key.Key_Escape)

        with_dialog(preview_cancel)
        check(to_hex(axes.lines[0].get_color()) == confirmed, "Cancel did not restore the colour")
        check(second.style == SECOND, "Cancel changed the stored style")
        shot(window, "second-cancelled")

        def apply(dialog):
            choose(dialog, "Pubblicazione")
            dialog.accept()

        with_dialog(apply)
        axes = second.result.figure.axes[0]
        expected = gsp.apply_preset(SECOND, {"version": 1, "name": "Pubblicazione", "style": PUBLICATION})
        check(second.style == expected, f"applied style {second.style}")
        check(axes.get_title() == "Calibrazione B" and axes.get_xscale() == "log", "title or scale changed")
        check(len(getattr(axes, "_tramastat_shapes", ())) == 1, "the shape was lost")
        check(to_hex(axes.lines[0].get_color()) == "#0b7a73", "applied colour missing")
        check(calls == [], f"engine called during preview/apply: {calls}")
        shot(window, "second-applied")
        for name in ("compute", "xy_series", "analyse"):
            for module in (project_module, window_module):
                if hasattr(module, "_smoke_" + name):
                    setattr(module, name, getattr(module, "_smoke_" + name))
                    delattr(module, "_smoke_" + name)

        saved = work / "styled.alab"
        window.project.save(saved)
        gsp.write_preset_file(work / "pubblicazione.json", gsp.PresetLibrary().load().get("Pubblicazione"))
        gsp.PresetLibrary().load().delete("Pubblicazione")
        open_session(saved)
        reopened = window.project.runs[1]
        check(reopened.style == expected, "the reopened project lost the style")
        window.open_sheet(("graph", 1))
        shot(window, "reopened")

        other = work / "secondo.alab"
        other.write_bytes((DATA / "sessione.alab").read_bytes())
        open_session(other)
        commit(0, {"title": "Calibrazione $ A"})
        window.open_sheet(("graph", 0))
        answers = []
        question = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: answers.pop(0) if answers else QMessageBox.StandardButton.No)

        def import_apply(dialog):
            check(dialog.import_path(work / "pubblicazione.json") is not None, "import failed")
            shouting = work / "maiuscole.json"
            shouting.write_text(json.dumps({"version": 1, "name": "PUBBLICAZIONE", "style": {"grid": False}}),
                                encoding="utf-8")
            check(dialog.import_path(shouting) is None, "a homonym was replaced without confirmation")
            truncated = work / "troncato.json"
            truncated.write_text((work / "pubblicazione.json").read_text(encoding="utf-8")[:-9], encoding="utf-8")
            check(dialog.import_path(truncated) is None, "a truncated file was imported")
            shot(dialog, "dialog-import-error")
            dialog.name.setText("")
            dialog.save_preset()
            check(not dialog.name_error.isHidden(), "empty name accepted")
            shot(dialog, "dialog-name-error")
            choose(dialog, "Pubblicazione")
            dialog.accept()

        try:
            with_dialog(import_apply)
        finally:
            QMessageBox.question = question
        run = window.project.runs[0]
        check(run.style == {"title": "Calibrazione $ A", **PUBLICATION}, f"second project style {run.style}")
        shot(window, "second-project")
        export_graph(run.result.figure, out / f"{tag}-secondo.svg")
        export_graph(run.result.figure, out / f"{tag}-secondo.pdf")
        svg = (out / f"{tag}-secondo.svg").read_text(encoding="utf-8")
        check("#0b7a73" in svg.lower(), "SVG without the style colour")
        check((out / f"{tag}-secondo.pdf").read_bytes().startswith(b"%PDF"), "PDF not written")

        gsp.library_path().write_text('{"version": 1, "presets": [', encoding="utf-8")

        def damaged(dialog):
            check(dialog.banner.objectName() == "errorBanner", "damaged library not reported")
            shot(dialog, "dialog-damaged")
            dialog.reject()

        with_dialog(damaged)
        check(gsp.library_path().read_text(encoding="utf-8") == '{"version": 1, "presets": [',
              "the damaged library was changed")
        check(errors == [], f"errors shown: {errors}")
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Figure styles smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             f" (QT_SCALE_FACTOR={os.environ.get('QT_SCALE_FACTOR', '1')}; emulated, not a native DPI setting)",
             f"Engine calls during preview and Apply: {len(calls)}",
             f"Screenshots: {len(shots)}", ""] + (problems or ["No problems found."])
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Figure styles smoke {tag}: {status} ({out})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
