"""Desktop acceptance of the Text group (cells, results, annotations), with screenshots of the new actions.

    python -m trama_qt.text_style_smoke OUT [--lang en|it] [--theme light|dark]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1024x768x24' ...``) and, for 150 %, with
``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels (``-screen 0 1536x1152x24``), which Qt sees as 1024×768
logical pixels. The scale is emulated, not a native DPI setting; the report says so.

It builds the synthetic table ``Misure`` (X, Risposta = 1, 3, 5, 7) with its linear regression and then, with the
real commands of the window: sets a background and a number format on B2:B4, formats them (14 pt, colour, bold,
centred), checks that the values 3, 5 and 7 are still numbers and that nothing was recalculated, restores the
text and checks that the background and the number format stayed; formats B2 and B3 differently, selects both and
turns italic on (mixed state, one undo step); checks that every command is reachable (toolbar, or the *More* menu
when the window is narrow); formats a result table; annotates the graph with ``CO2`` and ``10-3`` (subscript on
the 2, superscript on the -3), exports PNG, SVG and PDF, undoes and redoes; saves and reopens the project. ``OUT``
receives the screenshots, the exports, the reopenable ``casi-testo-celle.alab``, ``report.txt`` (platform, screen,
scale, timings, problems) and ``status.txt`` (PASS/FAIL).
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-text-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    import pandas as pd
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt
    from PySide6.QtWidgets import QApplication

    from analisi.i18n import set_language, tr
    from analisi.text_markup import SUBSCRIPT, SUPERSCRIPT
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-text-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.annotations import AnnotationEditor, GraphAnnotationsDialog
    from trama_qt.text_format import ACTIONS, TextFontDialog
    from trama_qt.window import MainWindow, export_graph

    problems, shots, timings = [], [], []
    tag = f"{args.lang}-{args.theme}"

    def check(condition, text):
        if not condition:
            problems.append(text)

    def settle():
        for _ in range(6):
            app.processEvents()
            time.sleep(0.02)

    def shot(widget, name):
        settle()
        path = out / f"{tag}-{len(shots) + 1:02d}-{name}.png"
        check(widget.grab().save(str(path)), f"{name}: screenshot not written")
        shots.append(path.name)

    def timed(label, function):
        start = time.perf_counter()
        result = function()
        timings.append(f"{label}: {(time.perf_counter() - start) * 1000:.1f} ms")
        return result

    window = MainWindow()
    errors = []
    window.error = lambda error: errors.append(str(error))
    window._ask = lambda *a, error=None, **k: errors.append(f"calculation failed: {error}")
    available = (window.screen() or app.primaryScreen()).availableGeometry()
    window.resize(min(1180, available.width()), min(768, available.height()))
    window.show()
    app.processEvents()
    theme.keep_on_screen(window)

    def wait():
        end = time.monotonic() + 120
        while window.job is not None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    def select(view, top, left, bottom, right):
        model = view.model()
        view.setCurrentIndex(model.index(top, left))
        view.selectionModel().select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                                     QItemSelectionModel.SelectionFlag.ClearAndSelect)
        settle()

    def popup(menu, name):
        menu.popup(window.mapToGlobal(QPoint(40, 60)))
        settle()
        shot(menu, name)
        menu.close()

    try:
        frame = pd.DataFrame({"X": [0, 1, 2, 3], "Risposta": [1, 3, 5, 7]})
        title, = window.project.add_tables({"Misure": frame})
        window.show_sheet("data", title)
        window.calculate_candidate(window.project.candidate(title, "Linear regression",
                                                            {"X": "X", "Y": "Risposta"}), frame, None)
        wait()
        window.show_sheet("data", title)
        settle()
        data, view = window.project.tables[title], window.sheet
        model = view.model()
        recalculated = []
        original_refresh = window.refresh_runs
        window.refresh_runs = lambda *args, **kwargs: (recalculated.append(args), original_refresh(*args, **kwargs))[1]

        # 1. Cells: background and number format first, then the text; Restore text keeps both.
        select(view, 1, 1, 3, 1)
        window.project.set_table_background(title, (1, 1, 3, 1), "#ffe385")
        window.project.set_table_number_format(title, ["Risposta"], {"mode": "fixed", "digits": 1})
        model.refresh_backgrounds()
        model.refresh_formats()
        timed("select B2:B4 and read the Text state", lambda: window.text_format.states())
        timed("apply 14 pt, colour, bold, centre to B2:B4", lambda: (
            window.text_format.apply({"size": 14, "color": "#126c65"}), window.actions["text_bold"].trigger(),
            window.actions["text_align_center"].trigger()))
        font = model.data(model.index(1, 1), Qt.ItemDataRole.FontRole)
        check(font is not None and font.bold() and font.pointSizeF() == 14.0, "B2 is not 14 pt bold")
        check(model.data(model.index(1, 1), Qt.ItemDataRole.ForegroundRole).color().name() == "#126c65",
              "B2 has not the chosen colour")
        check(model.data(model.index(1, 1)) == ("3,0" if args.lang == "it" else "3.0"),
              "the number format is not shown")
        check([data.raw["Risposta"].iat[row] for row in (1, 2, 3)] == [3, 5, 7]
              and pd.api.types.is_numeric_dtype(data.raw["Risposta"]), "the values 3, 5 and 7 are not numbers")
        check(recalculated == [], "the style recalculated an analysis")
        shot(window, "celle-formattate")
        timed("restore text", lambda: window.actions["text_restore"].trigger())
        check(not data.text_styles, "Restore text left a style")
        check(data.cell_backgrounds.get((1, "Risposta")) == "#ffe385", "Restore text removed the background")
        check(data.number_formats == {"Risposta": {"mode": "fixed", "digits": 1}},
              "Restore text removed the number format")
        window.undo()  # back to the formatted state: one step
        check(bool(data.text_styles), "undo of Restore text did not bring the formatting back")
        window.actions["text_restore"].trigger()
        check(not data.text_styles, "the second Restore text left a style")

        # 2. Mixed: B2 and B3 differently, both selected, italic.
        select(view, 1, 1, 1, 1)
        window.text_format.apply({"size": 12, "bold": True})
        select(view, 2, 1, 2, 1)
        window.text_format.apply({"color": "#aa0000", "underline": True})
        select(view, 1, 1, 2, 1)
        states = window.text_format.states()
        check(states["bold"].kind == "mixed" and states["color"].kind == "mixed", "the state is not mixed")
        check(window.actions["text_bold"].property("textState") == "mixed", "the Bold button does not show mixed")
        shot(window.toolbar, "gruppo-testo-misto")
        window.actions["text_italic"].trigger()
        check(data.text_styles.style_at("Risposta", 1) == {"size": 12, "bold": True, "italic": True}
              and data.text_styles.style_at("Risposta", 2) == {"color": "#aa0000", "underline": True,
                                                              "italic": True},
              "italic did not keep the other attributes")
        window.undo()
        check("italic" not in data.text_styles.style_at("Risposta", 1), "one undo did not take italic back")
        window.undo(redo=True)

        # 3. Reachability: every command is on the toolbar, or in the More menu when the window is narrow.
        window.toolbar._fit()
        controls = {**window.toolbar.buttons, **window.toolbar.fields}
        overflow = {action for group in window.toolbar.overflow.menu().actions() for action in group.menu().actions()}
        for key in ACTIONS:
            if key == "text_graph":
                continue
            button = controls.get(key)
            visible = (button is not None and button.isVisibleTo(window.toolbar)
                       and button.mapTo(window.toolbar, button.rect().bottomRight()).x() < window.toolbar.width())
            check(visible or window.actions[key] in overflow, f"{key} is missing from the toolbar and More menu")
        wide = window.width()
        window.resize(520, window.height())
        settle()
        window.toolbar._fit()
        check(window.toolbar.overflow.isVisible(), "the narrow window shows no More menu")
        group = [action.menu() for action in window.toolbar.overflow.menu().actions()
                 if action.text() == tr("ribbon.text_group")]
        check(bool(group) and {action.text() for action in group[0].actions()} >= {tr("command.text_bold")},
              "the Text commands are not in the More menu")
        shot(window, "finestra-stretta")
        if group:
            popup(group[0], "menu-altro-testo")
        window.resize(wide, window.height())
        settle()
        window.toolbar._fit()

        # 4. The menus and dialogs of the new commands.
        window.menuBar().actions()
        popup(window.command_menus["Change"], "menu-cambia")
        window.text_format.size_menu.aboutToShow.emit()
        popup(window.text_format.size_menu, "menu-dimensione")
        select(view, 1, 1, 3, 1)
        seen = []

        def font_dialog(dialog):
            seen.append(dialog.windowTitle())
            dialog.show()
            settle()
            shot(dialog, "finestra-carattere")
            dialog.reject()
            return dialog.DialogCode.Rejected
        with patch.object(TextFontDialog, "exec", font_dialog):
            window.actions["text_font"].trigger()
        check(bool(seen), "the font dialog did not open")

        # 5. A result table.
        window.open_sheet(("result", 0))
        wait()
        tabs = window.result_tabs
        result_view = tabs.currentWidget()
        select(result_view, 0, 0, 1, 2)
        window.actions["text_bold"].trigger()
        window.text_format.apply({"color": "#126c65"})
        run = window.project.runs[0]
        styles = window.project.tables[title].result_text_styles.get(run.slot, {})
        check(bool(styles), "the result table kept no style")
        check(result_view.model().flags(result_view.model().index(0, 1)) & Qt.ItemFlag.ItemIsEditable
              == Qt.ItemFlag.NoItemFlags, "the result values became editable")
        shot(window, "risultato-formattato")
        window.undo()
        window.undo()

        # 6. Annotation: CO2 and 10-3 with subscript on the 2 and superscript on the -3.
        window.open_sheet(("graph", 0))
        wait()
        axes = window.project.runs[0].result.figure.axes[0]
        editor = AnnotationEditor(window, axes)
        editor.text.set_content("CO2 e 10-3")
        cursor = editor.text.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(3, cursor.MoveMode.KeepAnchor)
        editor.text.setTextCursor(cursor)
        editor.subscript.click()
        cursor.setPosition(8)
        cursor.setPosition(10, cursor.MoveMode.KeepAnchor)
        editor.text.setTextCursor(cursor)
        editor.superscript.click()
        editor.text.selectAll()
        cursor = editor.text.textCursor()
        cursor.clearSelection()
        editor.text.setTextCursor(cursor)
        editor.show()
        shot(editor, "editor-annotazione")
        editor.accept()
        check(editor.result is not None and editor.result["text"] == "CO2 e 10-3"
              and editor.result["spans"] == [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]],
              f"the annotation record is wrong: {editor.result}")
        editor.deleteLater()

        def confirm(dialog):
            dialog.result = [editor.result]
            return dialog.DialogCode.Accepted
        with patch.object(GraphAnnotationsDialog, "exec", confirm):
            window.edit_annotations()
        settle()
        figure = window.project.runs[0].result.figure
        check(len(figure.axes[0].texts) == 1 and "_{" in figure.axes[0].texts[0].get_text(),
              "the annotation was not drawn with scripts")
        shot(window, "annotazione-apice-pedice")
        for suffix in ("png", "svg", "pdf"):
            export_graph(figure, out / f"{tag}-annotazione.{suffix}")
            check((out / f"{tag}-annotazione.{suffix}").stat().st_size > 500, f"{suffix} export is empty")
        window.undo()
        check(len(window.project.runs[0].result.figure.axes[0].texts) == 0, "undo did not remove the annotation")
        window.undo(redo=True)
        check(len(window.project.runs[0].result.figure.axes[0].texts) == 1, "redo did not bring it back")

        # 7. Save, reopen.
        saved = out / "casi-testo-celle.alab"
        window.project.save(saved)
        window.project.dirty = False
        window.close_project()
        window.open_path(saved)
        settle()
        wait()
        window.show_sheet("data", title)
        settle()
        reopened = window.project.tables[title]
        check(reopened.text_styles == data.text_styles, "the cell styles did not survive Save and reopen")
        check(window.project.runs[0].style.get("annotations", [{}])[0].get("spans")
              == [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]], "the annotation spans did not survive")
        shot(window, "progetto-riaperto")
        check(errors == [], f"errors shown: {errors}")
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Text group smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; scale override, not a native DPI setting)"
                if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
             f"Window {window.width()}×{window.height()}", f"Screenshots: {len(shots)}", *timings, ""]
    lines += problems or ["No problems found."]
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Text group smoke {tag}: {status} ({out})")
    for problem in problems:
        print("  -", problem)
    return 0 if status == "PASS" else 1


def run_dedicated(folder):
    folder = Path(folder)
    failures = [main([str(folder / f"{language}-{mode}"), "--lang", language, "--theme", mode])
                for language in ("en", "it") for mode in ("light", "dark")]
    status = "FAIL" if any(failures) else "PASS"
    (folder / "status.txt").write_text(status + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
