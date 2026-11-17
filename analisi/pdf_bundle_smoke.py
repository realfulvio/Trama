"""Desktop smoke check for File → Export multiple sheets to PDF… (0.58).

``tramastat.py --smoke`` calls :func:`check_pdf_bundle` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=pdf-bundle python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import pandas as pd
import pypdfium2 as pdfium
from pypdfium2 import raw

from .data import Dataset, save_project
from .pdf_bundle_dialog import PdfBundleDialog
from .presentation import Layout

TITLE = "Bundle data"
METHOD = "Scatter / confidence ellipse"
PAIR, SINGLE = "Pair layout", "Single layout"


def read_pdf(path):
    """[(size in pt, text, image objects)] for every page, closing each page explicitly."""
    pages = []
    with pdfium.PdfDocument(path) as document:
        for index in range(len(document)):
            page = document[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                finally:
                    textpage.close()
                images = len(list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])))
                pages.append((tuple(round(v, 2) for v in page.get_size()), text, images))
            finally:
                page.close()
    return pages


def check_pdf_bundle(root, app, directory, tools):
    """``tools`` carries the smoke helpers: capture, wait_for_calculation, filedialog."""
    wait, capture = tools.wait_for_calculation, tools.capture
    out = directory / "pdf-bundle"
    out.mkdir(exist_ok=True)
    log, problems = [], []

    def run_dialog(action, target, *, finish="ok", shot=None):
        """Drive the real dialog with ``action``; ``finish`` is "ok" or "cancel"."""
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, PdfBundleDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found

        def enter():
            dialog = find(root)
            if dialog is None:
                problems.append("PdfBundleDialog did not open")
                return
            try:
                action(dialog)
                dialog.update()
                if shot:
                    capture(dialog, shot)
                if finish == "ok":
                    dialog.ok()
                    if dialog.winfo_exists():
                        raise AssertionError("dialog stayed open: " + dialog.summary.cget("text"))
            except Exception as exception:
                problems.append(exception)
            finally:
                if dialog.winfo_exists():
                    dialog.cancel()

        root.after(200, enter)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)) as ask, \
                patch.object(app, "error") as error:
            app.export_pdf_bundle()
        assert not problems, problems
        return ask, error

    def choose(dialog, labels):
        """Select the listed entries (by position in the list) and refresh like a click would."""
        dialog.listbox.selection_clear(0, "end")
        for position in labels:
            dialog.listbox.selection_set(position)
        dialog.listbox.event_generate("<<ListboxSelect>>")
        dialog.update()

    # A fresh project: nothing to export, and the sheets of other open projects are not offered.
    app.new_project()
    root.update()
    with patch.object(app, "error") as error:
        app.export_pdf_bundle()
    assert error.called and "no calculated native graph" in str(error.call_args[0][0]), error.call_args

    # Two homonymous scatter graphs (Y and Y2) and two native layouts.
    data = Dataset(pd.DataFrame({"X": [1., 2, 3, 4, 5, 6], "Y": [1.2, 1.9, 3.2, 3.8, 5.1, 6.3],
                                "Y2": [6.1, 5.2, 3.9, 3.1, 2.2, .8], "Group": ["A", "A", "A", "B", "B", "B"]}))
    data.analyses.append((METHOD, {"X": "X", "Y": "Y", "Group": "Group"}))
    data.analyses.append((METHOD, {"X": "X", "Y": "Y2", "Group": "Group"}))
    path = directory / "pdf-bundle.alab"
    save_project(path, {TITLE: data}, layouts=[Layout(PAIR, 2, [(TITLE, 0), (TITLE, 1)]),
                                              Layout(SINGLE, 1, [(TITLE, 1)])])
    app.import_file(path)
    root.update()

    def calculate():
        for index, run in enumerate(app.runs):
            if run.result is None:
                app.open_sheet(("graph", index))
                wait()
        assert all(run.result and run.result.figure for run in app.runs)

    # Freshly opened: nothing is calculated, so the error names the sheets to recalculate.
    with patch.object(app, "error") as error:
        app.export_pdf_bundle()
    message = str(error.call_args[0][0])
    assert "Not calculated" in message and PAIR in message and SINGLE in message, message
    calculate()
    names = {run.name for run in app.runs}
    assert len(names) == 1, names  # same title, distinct sheets

    # The pair layout is the active page; the Inspector stays as it is.
    app.show("layout", 0)
    root.update()
    active_figure = app.layout_figure
    app.show("graph", 0)
    root.update()
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    graph = app.runs[0].result.figure
    before = (tuple(graph.get_size_inches()), graph.dpi, graph.canvas, graph.axes[0].get_xlim())
    options = [dict(run.options) for run in app.runs]
    dirty = app.dirty

    def unchanged(label):
        assert (tuple(graph.get_size_inches()), graph.dpi, graph.canvas, graph.axes[0].get_xlim()) == before, label
        assert [dict(run.options) for run in app.runs] == options and app.dirty == dirty, label
        assert app.inspector is inspector, label

    # Reorder, check the listed order and vector note, then cancel.
    skipped = out / "never.pdf"

    def reorder(dialog):
        labels = list(dialog.listbox.get(0, "end"))
        assert labels == [f"Graph · {METHOD} of {TITLE}", f"Graph · {METHOD} of {TITLE} (2)"] + [f"Layout · {PAIR}", f"Layout · {SINGLE}"], labels
        assert dialog.summary.cget("text").startswith("1 page"), dialog.summary.cget("text")
        choose(dialog, [1, 3])
        dialog.move(-1)
        dialog.move(-1)
        assert [entry.ref for entry in dialog.selected()] == [("graph", 1), ("layout", 1)], dialog.selected()
        assert dialog.listbox.get(0) == f"Graph · {METHOD} of {TITLE} (2)" and dialog.order == [1, 0, 3, 2], dialog.order
        note = dialog.note.cget("text")
        assert "layout panels retain vector graphics" in note and "embedded images" not in note, note
        assert "2 pages" in dialog.summary.cget("text")
    ask, _ = run_dialog(reorder, skipped, finish="cancel", shot="window-pdf-bundle-reorder.png")
    assert not ask.called and not skipped.exists()
    unchanged("cancel")

    # Invalid choices keep the dialog open and point at the field.
    def invalid(dialog):
        choose(dialog, [])
        assert dialog.validate() is False and "Select at least one" in dialog.summary.cget("text")
        assert dialog.focus_lastfor() == dialog.listbox, dialog.focus_lastfor()
        choose(dialog, [0, 2])
        dialog.width.set("40")
        dialog.update()
        assert dialog.validate() is False and PAIR in dialog.summary.cget("text"), dialog.summary.cget("text")
        assert dialog.focus_lastfor() == dialog.width_entry, dialog.focus_lastfor()
        capture(dialog, "window-pdf-bundle-width-error.png")
        dialog.width.set("abc")
        assert dialog.validate() is False
    ask, _ = run_dialog(invalid, skipped, finish="cancel")
    assert not ask.called and not skipped.exists()
    unchanged("invalid")

    # Three pages: Y2 graph, Y graph, then the single layout (not the active one), at original size.
    target = out / "three-pages.pdf"

    def three(dialog):
        choose(dialog, [1])
        dialog.move(-1)
        choose(dialog, [0, 1, 3])
        text = dialog.summary.cget("text")
        assert text.startswith("3 pages") and text.index(f"3. Layout · {SINGLE}") > 0, text
    run_dialog(three, target, shot="window-pdf-bundle-dialog.png")
    pages = read_pdf(target)
    assert len(pages) == 3, pages
    (size_a, text_a, img_a), (size_b, text_b, img_b), (size_c, text_c, img_c) = pages
    assert "Y2" in text_a and "Y2" not in text_b, (text_a, text_b)
    assert img_a == img_b == img_c == 0, (img_a, img_b, img_c)
    assert SINGLE in text_c and PAIR not in text_c and "Y2" in text_c, text_c
    # Original width: each graph page has the size of its own figure (the on-screen size it was drawn at).
    for size, run in ((size_a, app.runs[1]), (size_b, app.runs[0])):
        want = tuple(round(float(v) * 72, 2) for v in run.result.figure.get_size_inches())
        assert size == want, (size, want)
    assert size_c == (302.4, 259.2), size_c  # one column, not the 2-column active layout
    assert app.layout_figure is active_figure or app.layout_figure is None
    unchanged("export")
    log.append(f"three-pages.pdf {[size for size, _, _ in pages]} images {[n for _, _, n in pages]}")

    # Common width: every page 76.2 mm wide with its own aspect ratio; transparent background accepted.
    resized = out / "three-pages-76mm.pdf"

    def width(dialog):
        choose(dialog, [0, 1, 3])
        dialog.width.set("76,2")
        dialog.transparent.set(True)
    run_dialog(width, resized)
    sizes = [size for size, _, _ in read_pdf(resized)]
    assert all(abs(w - 216) < .02 for w, _ in sizes), sizes
    assert abs(sizes[2][1] - 216 * 259.2 / 302.4) < .05, sizes
    log.append(f"three-pages-76mm.pdf {sizes}")
    unchanged("resized")

    # Save, reopen: the graphs are not calculated until opened; then export again.
    app.show("graph", 0)
    root.update()
    if app.inspector is not None:
        app.inspector.cancel()
    assert app.save()
    app.import_file(app.path)
    root.update()
    with patch.object(app, "error") as error:
        app.export_pdf_bundle()
    assert "Not calculated" in str(error.call_args[0][0])
    calculate()
    reopened = out / "reopened.pdf"
    run_dialog(lambda dialog: choose(dialog, [0, 1, 2, 3]), reopened)
    pages = read_pdf(reopened)
    assert [size for size, _, _ in pages][2:] == [(604.8, 259.2), (302.4, 259.2)], pages
    log.append(f"reopened.pdf {len(pages)} pages")

    # Edit a value: the linked graphs recalculate and the new export shows the new data.
    first = pages[1][1]
    app.show("data", TITLE)
    columns = list(app.tables[TITLE].raw.columns)
    app.edit_cell(0, columns.index("Y2"), "19")
    wait()
    assert all(run.result and run.result.figure for run in app.runs)
    edited = out / "edited.pdf"
    run_dialog(lambda dialog: choose(dialog, [0, 1, 2, 3]), edited)
    pages = read_pdf(edited)
    assert len(pages) == 4 and pages[1][1] != first, "edited data not exported"
    assert "15" in pages[1][1] and "15" not in first, pages[1][1]  # the Y2 axis now reaches 19
    log.append("edited.pdf Y2 axis follows the edited value")

    app.show("layout", 1)
    root.update()
    capture(root, "window-pdf-bundle-opened.png")
    (out / "pdf-bundle.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    app.dirty = False
