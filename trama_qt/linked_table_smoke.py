"""Desktop acceptance of Insert → Linked table…, with screenshots of the new actions.

    python -m trama_qt.linked_table_smoke OUT [--lang en|it] [--theme light|dark]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1024x768x24' ...``) and, for 150 %, with
``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels (``-screen 0 1536x1152x24``), which Qt sees as 1024×768
logical pixels. The scale is emulated, not a native DPI setting; the report says so.

It builds the synthetic table ``Misure`` (X, Risposta = 1, 3, 5, 7) with its linear regression (slope 2) and then,
with the real commands of the window:

* *tabella-collegata*: selects the slope on the result table and places it, with *Linked table from selection…*,
  as a Linked table and as a Copy on the graph and on the layout page; changes B4 from 7 to 9 and recalculates:
  the linked cells read 2.6 and the copies still 2, on the graph, on the layout, in the PNG, SVG, PDF and the
  multi-sheet PDF (the numbers are read back from the files); saves and reopens;
* *sorgente-mancante*: removes the analysis a linked table reads (a state, never another recipe; the copy keeps its
  numbers), replaces it by an identical new analysis (still not found), saves and reopens, makes the source fail
  (an explicit state) and undoes the edit (the table recovers);
* *vettoriale*: a graph with a table inside the layout and a table directly on the layout page: each table once, in
  the expected place, with text and rules as vectors in the multi-sheet PDF, the single PDF and the SVG.

``OUT`` receives the screenshots, the exports, the reopenable ``casi-tabella-collegata.alab``, ``report.txt``
(platform, screen, scale, timings, problems) and ``status.txt`` (PASS/FAIL).
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SVG = "{http://www.w3.org/2000/svg}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-table-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    import pandas as pd
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint
    from PySide6.QtWidgets import QApplication, QDialog

    from analisi import linked_tables as lt
    from analisi.i18n import set_language, tr
    from analisi.presentation import Layout
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-table-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.linked_tables import LinkedTableDialog, LinkedTablesDialog
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

    def texts(figure, numbers=False):
        """The words of the tables of a figure; ``numbers`` keeps the cell values and drops the titles."""
        found = [child.get_text() for artist in figure.artists if isinstance(artist, lt.LinkedTableArtist)
                 for child in artist._children if hasattr(child, "get_text") and child.get_text()]
        return [text for text in found if _is_number(text)] if numbers else found

    def _is_number(text):
        try:
            float(text)
        except ValueError:
            return False
        return True

    def report(owner=None):
        return [(kind[0], record["mode"], resolved.state, resolved.cells)
                for kind, record, resolved in window.project.linked_table_report()
                if owner is None or kind[0] == owner]

    def words(path, page=0):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as document:
            sheet = document[page]
            try:
                return sheet.get_textpage().get_text_range().split()
            finally:
                sheet.close()

    def pdf_picture(path, name, page=0):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as document:
            sheet = document[page]
            try:
                sheet.render(scale=1.2).to_pil().save(out / f"{tag}-{name}.png")
            finally:
                sheet.close()

    def svg_tables(path):
        root = ET.parse(path).getroot()
        groups = [g for g in root.iter(SVG + "g") if (g.get("id") or "").startswith(("tramastat-table-",
                                                                                      "layout-tables"))
                  or "tramastat-table-" in (g.get("id") or "")]
        return root, groups

    def dialog_run(name, *, place=None, copy=False, position=None, screenshot=True):
        """What the person does in the window that opens: look, choose where it goes, press OK."""
        def run(dialog):
            dialog.show()
            settle()
            check(dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled(), f"{name}: OK is disabled")
            geometry = dialog.frameGeometry()
            screen_box = (dialog.screen() or app.primaryScreen()).availableGeometry()
            check(screen_box.contains(geometry.topLeft()) and geometry.height() <= screen_box.height() + 2,
                  f"{name}: the window does not fit the screen ({geometry.width()}×{geometry.height()})")
            if place is not None:
                dialog.choose_target(place)
            dialog.copy.setChecked(copy)
            if position is not None:
                dialog.x.setValue(position[0] * 100)
                dialog.y.setValue(position[1] * 100)
            if screenshot:
                shot(dialog, name)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected
        return run

    try:
        frame = pd.DataFrame({"X": [0, 1, 2, 3], "Risposta": [1, 3, 5, 7]})
        title, = window.project.add_tables({"Misure": frame})
        window.show_sheet("data", title)
        window.calculate_candidate(window.project.candidate(title, "Linear regression",
                                                            {"X": "X", "Y": "Risposta"}), frame, None)
        wait()
        window.project.put_layout(Layout("Risultati in figura", 1, [(title, 0)]))
        window.refresh()
        window.show_sheet("data", title)
        settle()
        project = window.project
        check(bool(project.layouts), "the project has no layout")
        check(project.runs[0].result is not None, "the regression was not calculated")

        # 0. The commands: in the Insert menu, enabled where they can be used.
        listed = [action.text() for action in window.command_menus["Insert"].actions()]
        check(tr("command.linked_table") in listed and tr("command.linked_table_selection") in listed,
              "the Insert menu does not list the linked table commands")
        popup(window.command_menus["Insert"], "menu-inserisci")
        check(not window.actions["linked_table"].isEnabled(), "Linked table… is on for a worksheet")
        select(window.sheet, 1, 1, 2, 1)
        check(window.actions["linked_table_selection"].isEnabled(), "the selection command is off with cells selected")
        shot(window, "foglio-dati-selezione")

        # 1. tabella-collegata: the slope of the regression, linked and as a copy, on the graph and on the layout.
        def slope_view():
            window.open_sheet(("result", 0))
            settle()
            tabs = window.result_tabs
            names = [tabs.tabText(index) for index in range(tabs.count())]
            tabs.setCurrentIndex(names.index("Regression"))
            view = tabs.currentWidget()
            model = view.model()
            return view, [model.data(model.index(r, 0)) for r in range(model.rowCount())].index("Slope")

        view, row = slope_view()
        select(view, row, 0, row, 0)
        window.insert_linked_table_from_selection()
        check(errors == [tr("linked_table.row_titles")], f"the titles column was not refused: {errors}")
        errors.clear()
        select(view, row, 1, row, 1)
        shot(window, "risultati-pendenza-selezionata")

        def place_slope(name, place, *, copy, position, screenshot):
            view, row = slope_view()
            select(view, row, 1, row, 1)
            with patch.object(LinkedTableDialog, "exec", dialog_run(name, place=place, copy=copy,
                                                                     position=position, screenshot=screenshot)):
                timed(f"insert {name}", window.insert_linked_table_from_selection)

        place_slope("dialogo-collegata-grafico", ("graph", 0), copy=False, position=(.05, .08), screenshot=True)
        place_slope("copia-grafico", ("graph", 0), copy=True, position=(.55, .08), screenshot=False)
        place_slope("collegata-layout", ("layout", 0), copy=False, position=(.74, .01), screenshot=False)
        place_slope("copia-layout", ("layout", 0), copy=True, position=(.74, .12), screenshot=False)
        check(errors == [], f"errors shown: {errors}")
        check(report() == [("graph", "linked", "ok", (("2",),)), ("graph", "copy", "ok", (("2",),)),
                           ("layout", "linked", "ok", (("2",),)), ("layout", "copy", "ok", (("2",),))],
              f"before the edit: {report()}")
        window.show_sheet("graph", 0)
        shot(window, "grafico-con-tabelle-prima")
        check(texts(project.runs[0].result.figure, True) == ["2", "2"], "the graph tables before the edit are not 2 and 2")
        window.show_sheet("layout", 0)
        shot(window, "layout-con-tabelle-prima")

        # The list of the tables of the graph (Insert → Linked table…): cancel leaves them alone.
        window.show_sheet("graph", 0)

        def list_run(dialog):
            dialog.show()
            settle()
            check(dialog.table.rowCount() == 2, "the graph list does not show its two tables")
            check(dialog.table.item(0, 3).text() == tr("linked_table.state_ok"), "the state column is not 'up to date'")
            dialog.table.selectRow(0)
            shot(dialog, "elenco-tabelle-grafico")
            return QDialog.DialogCode.Rejected
        with patch.object(LinkedTablesDialog, "exec", list_run):
            window.edit_linked_tables()
        check(len(project.runs[0].style[lt.TABLES]) == 2, "Cancel changed the tables")

        # B4 from 7 to 9: the slope becomes 2.6; the linked cells follow, the copies keep 2.
        window.show_sheet("data", title)
        sheet_model = window.sheet.model()
        timed("edit B4 and recalculate", lambda: (sheet_model.setData(sheet_model.index(3, 1), "9"), wait()))
        settle()
        check(report() == [("graph", "linked", "ok", (("2.6",),)), ("graph", "copy", "ok", (("2",),)),
                           ("layout", "linked", "ok", (("2.6",),)), ("layout", "copy", "ok", (("2",),))],
              f"after the edit: {report()}")
        window.show_sheet("graph", 0)
        shot(window, "grafico-con-tabelle-dopo")
        check(texts(project.runs[0].result.figure, True) == ["2.6", "2"], "the graph tables after the edit are not 2.6, 2")
        window.show_sheet("layout", 0)
        shot(window, "layout-con-tabelle-dopo")
        layout = project.layouts[0]
        page_figure = project.layout_figure(layout)
        check(texts(page_figure, True) == ["2.6", "2"], f"the layout page tables: {texts(page_figure)}")

        graph_figure = project.runs[0].result.figure
        for suffix, settings in (("png", {"format": "png", "dpi": 150}), ("pdf", {"format": "pdf"}),
                                 ("svg", {"format": "svg", "svg_text": "text"})):
            export_graph(graph_figure, out / f"{tag}-grafico.{suffix}", settings)
            project.export_layout(layout, out / f"{tag}-layout.{suffix}",
                                  {**settings, "dpi": 150} if suffix == "png" else settings)
        pages = timed("multi-sheet PDF", lambda: project.export_pdf_pages(
            [("layout", 0), ("graph", 0)], out / f"{tag}-multiplo.pdf", {"format": "pdf"}, ["Layout", "Grafico"]))
        check(pages == 2, f"the multi-sheet PDF has {pages} pages")
        for path in ("grafico.png", "layout.png", "grafico.pdf", "layout.pdf", "grafico.svg", "layout.svg",
                     "multiplo.pdf"):
            check((out / f"{tag}-{path}").exists() and (out / f"{tag}-{path}").stat().st_size > 800,
                  f"{path} is empty")
        # The same numbers everywhere: 2.6 on the graph, 2.6 twice on the layout (graph panel + page).
        check(words(out / f"{tag}-grafico.pdf").count("2.6") == 1, "graph PDF: the linked number is not 2.6 once")
        for name, page in (("layout.pdf", 0), ("multiplo.pdf", 0)):
            check(words(out / f"{tag}-{name}", page).count("2.6") == 2, f"{name}: the linked numbers are not 2.6 ×2")
        check(words(out / f"{tag}-multiplo.pdf", 1).count("2.6") == 1, "multi-sheet PDF page 2: not 2.6 once")
        for name in ("grafico.svg", "layout.svg"):
            root = ET.parse(out / f"{tag}-{name}").getroot()
            found = ["".join(t.itertext()) for t in root.iter(SVG + "text")]
            check(found.count("2.6") == (1 if name == "grafico.svg" else 2), f"{name}: 2.6 appears {found.count('2.6')}")
        pdf_picture(out / f"{tag}-layout.pdf", "layout-pdf")

        # The project is saved and reopened: both modes come back, the linked cell still reads the same analysis.
        saved = out / "casi-tabella-collegata.alab"
        project.save(saved)
        project.dirty = False
        window.close_project()
        window.open_path(saved)
        settle()
        wait()
        project = window.project
        for index, run in enumerate(project.runs):
            if run.result is None:
                window.refresh_runs([run])
                wait()
        check([c[1:3] for c in report()] == [("linked", "ok"), ("copy", "ok"), ("linked", "ok"), ("copy", "ok")],
              f"after reopening: {report()}")
        check([c[3] for c in report()] == [(("2.6",),), (("2",),), (("2.6",),), (("2",),)],
              f"after reopening the numbers are {[c[3] for c in report()]}")
        window.show_sheet("graph", 0)
        shot(window, "progetto-riaperto")

        # 2. sorgente-mancante: a second analysis the tables read, then removed, replaced, failed.
        second = project.candidate(title, "Descriptive statistics", {"Variables": ["Risposta"]})
        from trama_qt.project import compute
        project.add_result(second, compute(second, project.tables[title].frame(mask_excluded=True)))
        slot = len(project.runs) - 1
        run2 = project.runs[slot]
        name = next(iter(run2.result.tables))
        choice = next(c for c in project.table_source_choices()
                      if c["kind"] == "result" and c["analysis"] == run2.uid and c["table"] == name)
        linked = project.table_record(choice, (0, 0, 0, 0), mode="linked", position=(.05, .5))
        copy = project.table_record(choice, (0, 0, 0, 0), mode="copy", position=(.55, .5))
        window.commit_linked_tables(("graph", 0), [*project.runs[0].style[lt.TABLES], linked, copy])
        expected = report("graph")[-2:]
        check([c[2] for c in expected] == ["ok", "ok"], f"the second source is not ok: {expected}")
        shown = expected[1][3]
        project.delete_sheet(("result", slot))
        window.refresh()
        window.show_sheet("graph", 0)
        gone = report("graph")[-2:]
        check([(c[1], c[2]) for c in gone] == [("linked", "missing"), ("copy", "ok")], f"source removed: {gone}")
        check(gone[1][3] == shown, "the copy lost its numbers")
        check(tr("linked_table.state.missing") in texts(project.runs[0].result.figure), "no 'source not available'")
        shot(window, "origine-mancante")
        # A new analysis with the same recipe is another analysis: the table does not move onto it.
        again = project.candidate(title, "Descriptive statistics", {"Variables": ["Risposta"]})
        project.add_result(again, compute(again, project.tables[title].frame(mask_excluded=True)))
        window.refresh()
        replaced = report("graph")[-2:]
        check([(c[1], c[2]) for c in replaced] == [("linked", "missing"), ("copy", "ok")],
              f"the table moved onto a replacement: {replaced}")
        project.save(out / "origine-mancante.alab")
        window.show_sheet("graph", 0)

        # The state is the same after Save and reopen; the copy still holds its numbers.
        project.dirty = False
        window.close_project()
        window.open_path(out / "origine-mancante.alab")
        settle()
        wait()
        project = window.project
        for run in project.runs:
            if run.result is None:
                window.refresh_runs([run])
                wait()
        reopened = report("graph")[-2:]
        check([(c[1], c[2]) for c in reopened] == [("linked", "missing"), ("copy", "ok")],
              f"missing source after reopening: {reopened}")
        check(reopened[1][3] == shown, "the copy lost its numbers after reopening")
        window.show_sheet("graph", 0)
        shot(window, "origine-mancante-riaperto")

        # A failing source is an explicit state; undoing the edit brings the table back.
        window.show_sheet("data", title)
        select(window.sheet, 1, 0, 3, 1)
        window.actions["exclude"].trigger()      # one point left: the regression cannot be fitted
        wait()
        settle()
        failing = [c for c in report() if c[0] == "graph" and c[1] == "linked" and c[2] != "missing"]
        check(failing and failing[0][2] in {"error", "pending", "changed"} and failing[0][3] != (("2.6",),),
              f"a failing source is not a state: {report()}")
        window.show_sheet("graph", 0)
        shot(window, "origine-in-errore")
        window.show_sheet("data", title)
        window.undo()
        wait()
        settle()
        recovered = [c for c in report() if c[0] == "graph" and c[1] == "linked"]
        check(recovered and recovered[0][2] == "ok" and recovered[0][3] == (("2.6",),),
              f"the table did not recover after undo: {recovered}")
        window.show_sheet("graph", 0)

        # 3. vettoriale: the graph with its tables inside the layout, and a table on the layout page itself.
        layout = project.layouts[0]
        for path in ("vettoriale-layout.pdf", "vettoriale-layout.svg", "vettoriale-multiplo.pdf"):
            (out / f"{tag}-{path}").unlink(missing_ok=True)
        project.export_layout(layout, out / f"{tag}-vettoriale-layout.pdf", {"format": "pdf"})
        project.export_layout(layout, out / f"{tag}-vettoriale-layout.svg", {"format": "svg", "svg_text": "text"})
        project.export_pdf_pages([("layout", 0)], out / f"{tag}-vettoriale-multiplo.pdf", {"format": "pdf"}, ["Layout"])
        single, multi = words(out / f"{tag}-vettoriale-layout.pdf"), words(out / f"{tag}-vettoriale-multiplo.pdf")
        check(single.count("2.6") == 2 and multi.count("2.6") == 2,
              f"vector text: single {single.count('2.6')}, multi {multi.count('2.6')} (2 and 2 expected)")
        root, groups = svg_tables(out / f"{tag}-vettoriale-layout.svg")
        check(len(groups) >= 3, f"SVG: {len(groups)} table groups (graph tables ×3 and the page ones expected)")
        check(all(list(g.iter(SVG + "path")) or list(g.iter(SVG + "line")) or list(g.iter(SVG + "rect"))
                  for g in groups), "SVG: a table has no rules")
        check(any(g.get("id") == "layout-tables" for g in groups), "SVG: no layout-tables group")
        pdf_picture(out / f"{tag}-vettoriale-multiplo.pdf", "vettoriale-pdf")
        window.show_sheet("layout", 0)
        shot(window, "layout-vettoriale")
        check(errors == [], f"errors shown: {errors}")
        project.save(out / "casi-tabella-collegata-finale.alab")
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Linked table smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; scale override, not a native DPI setting)"
                if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
             f"Window {window.width()}×{window.height()}", f"Screenshots: {len(shots)}", *timings, ""]
    lines += problems or ["No problems found."]
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Linked table smoke {tag}: {status} ({out})")
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
