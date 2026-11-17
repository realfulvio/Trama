"""Desktop smoke for the native graph shapes editor (lines, rectangles, ellipses).

``tramastat.py --smoke`` calls :func:`check_graph_shapes` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=graph-shapes python tramastat.py --smoke DIR``.

Synthetic data only. Exports and the project stay in ``DIR/graph-shapes``; screenshots in ``DIR``.
"""
from copy import deepcopy
import json
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
from PIL import Image
import pypdfium2 as pdfium
from pypdfium2 import raw as pdfraw

from . import i18n
from .data import Dataset, save_project
from .figure_export_dialog import FigureExportDialog
from .graph_annotation_dialog import AnnotationEditor, GraphAnnotationsDialog
from .graph_annotations import ANNOTATIONS
from .graph_dialog import GraphFormatDialog
from .graph_shape_dialog import GraphShapesDialog, ShapeEditor
from .graph_shapes import KINDS, LAYERS, LINE_STYLES, SHAPES, UNITS

SVG = "{http://www.w3.org/2000/svg}"
TITLE = "Shape data"
LABEL = "Shape note < 5 – città"
SCREEN = (1024, 768)


def _shape_ids(figure):
    return [artist.get_gid() for artist in figure.axes[0]._tramastat_shapes]


def _pdf_objects(path):
    """(text, path objects, image objects) of the first page, descending into Form XObjects."""
    document = pdfium.PdfDocument(str(path))
    try:
        page = document[0]
        try:
            textpage = page.get_textpage()
            try:
                text = " ".join(textpage.get_text_range().split())
            finally:
                textpage.close()
            types = [item.type for item in page.get_objects(max_depth=15)]
        finally:
            page.close()
    finally:
        document.close()
    return text, types.count(pdfraw.FPDF_PAGEOBJ_PATH), types.count(pdfraw.FPDF_PAGEOBJ_IMAGE)


def _fits(dialog, buttons):
    dialog.update()
    assert dialog.winfo_width() <= SCREEN[0] and dialog.winfo_height() <= SCREEN[1], (
        dialog.winfo_width(), dialog.winfo_height())
    bottom = dialog.winfo_rooty() + dialog.winfo_height()
    for button in buttons:
        assert button.winfo_viewable(), button
        assert button.winfo_rooty() + button.winfo_height() <= bottom, button


def check_graph_shapes(kit):
    """``kit``: app, root, directory, capture, drive_dialog(type, action), wait_for_calculation, filedialog,
    LayoutDialog."""
    original = i18n.active_language()
    i18n.set_language("en")
    try:
        _check(kit)
    finally:
        i18n.set_language(original)


def _check(kit):
    app, root, wait, capture = kit.app, kit.root, kit.wait_for_calculation, kit.capture
    out = kit.directory / "graph-shapes"
    out.mkdir(exist_ok=True)
    path = out / "graph-shapes.alab"
    dataset = Dataset(pd.DataFrame({"Dose": [1., 2., 4., 6., 8.], "Response": [2.1, 3.8, 8.2, 11.7, 15.2]}))
    dataset.analyses.append(("Linear regression", {"X": "Dose", "Y": "Response"}))
    dataset.analyses.append(("Linear regression", {"X": "Dose", "Y": "Response"}))
    save_project(path, {TITLE: dataset})
    app.import_file(path)
    app.open_sheet(("graph", 0))
    wait()
    run = app.runs[0]
    app.dirty = False

    def drive_editor(fill, *, shot=None, error=None):
        """Queue the next ShapeEditor: ``fill(editor)`` then OK. ``error`` = (field, value) tried first."""
        def act(editor):
            _fits(editor, (editor.preview_button, editor.ok_button, editor.cancel_button))
            fill(editor)
            if error is not None:
                field, wrong = error
                kept = editor.fields[field].get()
                editor.fields[field].set(wrong)
                editor.ok()
                editor.update()
                assert editor.winfo_exists(), "an invalid shape closed the editor"
                assert editor.problem.cget("text"), "no message for the invalid field"
                assert editor.focus_lastfor() is editor.widgets[field], (editor.focus_lastfor(), field)
                assert editor.fields[field].get() == wrong, "the typed value was not kept"
                capture(editor, "window-graph-shapes-editor-error.png")
                editor.fields[field].set(kept)
            if shot:
                editor.update()
                capture(editor, shot)
            editor.ok()
            assert not editor.winfo_exists(), editor.problem.cget("text")
        kit.drive_dialog(ShapeEditor, act)

    def line(editor):
        for name, value in zip(("x1", "y1", "x2", "y2"), ("0,1", "0,15", "0,9", "0,85")):
            editor.fields[name].set(value)
        editor.fields["stroke"].set("#c62b37")
        editor.fields["width"].set("2,5")

    def rectangle(editor):
        box = editor.widgets["kind"]
        box.current(KINDS.index("rectangle"))
        box.event_generate("<<ComboboxSelected>>")
        # Inverted corners are stored as min/max.
        for name, value in zip(("x1", "y1", "x2", "y2"), ("0.8", "0.75", "0.3", "0.2")):
            editor.fields[name].set(value)
        editor.fields["fill"].set("#dce8f5")
        editor.fields["alpha"].set("0,6")
        editor.fields["layer"].set("below")
        editor.fields["line_style"].set("dashed")

    def ellipse(editor):
        editor.fields["kind"].set("ellipse")
        editor.fields["units"].set("data")
        for name, value in zip(("x1", "y1", "x2", "y2"), ("2", "3", "5", "9,5")):
            editor.fields[name].set(value)
        editor.fields["stroke"].set("#207a4b")
        editor.fields["fill"].set("")

    def add_three(dialog, shots=True):
        drive_editor(line, shot="window-graph-shapes-editor.png" if shots else None)
        dialog.add()
        drive_editor(rectangle, error=("width", "13") if shots else None)
        dialog.add()
        drive_editor(ellipse)
        dialog.add()
        assert [record["kind"] for record in dialog.records] == ["line", "rectangle", "ellipse"], dialog.records
        assert dialog.records[1]["points"] == [[.3, .2], [.8, .75]], dialog.records[1]

    # 1. From the Insert menu: build three shapes, duplicate, reorder, remove, preview, then Cancel.
    def first(dialog):
        _fits(dialog, (dialog.apply_button, dialog.cancel_button))
        add_three(dialog)
        ids = [record["id"] for record in dialog.records]
        dialog.tree.selection_set("2")
        dialog.duplicate()
        assert len(dialog.records) == 4 and dialog.records[3]["id"] not in ids, dialog.records
        dialog.move(-1)
        assert dialog.records[2]["id"] not in ids and dialog.records[3]["id"] == ids[2]
        dialog.move(1)
        dialog.tree.selection_set("3")
        dialog.remove()
        assert [record["id"] for record in dialog.records] == ids
        dialog.tree.selection_set("0")
        dialog.move(1)
        dialog.move(-1)
        assert [record["id"] for record in dialog.records] == ids
        dialog.preview()
        root.update()
        assert len(run.result.figure.axes[0]._tramastat_shapes) == 3
        assert SHAPES not in (run.style or {}) and not app.dirty, "a preview changed the confirmed graph"
        dialog.update()
        capture(dialog, "window-graph-shapes-list.png")
        capture(root, "window-graph-shapes-preview.png")
        dialog.cancel()

    popup, index = app.menu_entries["Insert", "Graph shapes…"]
    kit.drive_dialog(GraphShapesDialog, first)
    popup.invoke(index)
    root.update()
    assert SHAPES not in (run.style or {}) and not run.result.figure.axes[0]._tramastat_shapes, (
        run.style, run is app.runs[0], len(run.result.figure.axes[0]._tramastat_shapes))
    assert not app.dirty, "Cancel made the project dirty"
    capture(root, "window-graph-shapes-cancelled.png")

    # 2. From the graph bar drawing menu: three shapes and Apply.
    def bar_menu():
        stack = [app.page]
        while stack:
            widget = stack.pop()
            if widget.winfo_class() == "TMenubutton" and widget.cget("menu"):
                menu=widget.nametowidget(widget.cget("menu"))
                if menu.entrycget(0,"label") == i18n.tr("shape.canvas.manage"):
                    return menu
            stack.extend(widget.winfo_children())
        raise AssertionError("Graph shapes menu missing from the graph bar")

    def second(dialog):
        add_three(dialog, shots=False)
        dialog.apply_button.invoke()

    kit.drive_dialog(GraphShapesDialog, second)
    bar_menu().invoke(0)
    root.update()
    run = app.runs[0]
    records = deepcopy(run.style[SHAPES])
    assert len(records) == 3 and app.dirty
    assert _shape_ids(run.result.figure) == ["tramastat-shape-" + record["id"] for record in records]
    for record in records:
        assert record["kind"] in KINDS and record["units"] in UNITS
        assert record["line_style"] in LINE_STYLES and record["layer"] in LAYERS
    assert records[0]["width"] == 2.5 and records[1]["alpha"] == .6 and records[2]["fill"] is None
    capture(root, "window-graph-shapes-applied.png")

    # Applying the same list again neither accumulates artists nor dirties a saved project.
    app.dirty = False
    for _ in range(3):
        kit.drive_dialog(GraphShapesDialog, lambda dialog: dialog.apply_button.invoke())
        app.edit_graph_shapes()
        root.update()
    assert len(app.runs[0].result.figure.axes[0]._tramastat_shapes) == 3 and not app.dirty

    # 3. A text annotation, the Inspector title and the Format Graph reset keep the shapes.
    def annotate(dialog):
        def text(editor):
            editor.text.insert("1.0", LABEL)
        kit.drive_dialog(AnnotationEditor, text)
        dialog.add()

    kit.drive_dialog(GraphAnnotationsDialog, annotate)
    app.edit_graph_annotations()
    run = app.runs[0]
    assert run.style[SHAPES] == records and len(run.style[ANNOTATIONS]) == 1
    app.toggle_inspector()
    inspector = app.inspector
    inspector.vars["title"].set("Shapes and data")
    inspector._now("title")
    assert inspector.apply(), inspector.status.cget("text")
    inspector.cancel_button.invoke()
    run = app.runs[0]
    assert run.style["title"] == "Shapes and data" and run.style[SHAPES] == records
    assert len(run.result.figure.axes[0]._tramastat_shapes) == 3

    def reset():
        dialog = next(child for child in root.winfo_children() if isinstance(child, GraphFormatDialog))
        dialog._reset()

    root.after(200, reset)
    app.format_graph()
    run = app.runs[0]
    assert set(run.style) == {SHAPES, ANNOTATIONS}, run.style
    assert run.style[SHAPES] == records
    annotation = deepcopy(run.style[ANNOTATIONS])
    assert len(run.result.figure.axes[0]._tramastat_shapes) == 3

    # 4. Italian labels on the same dialog: the stored record stays canonical.
    i18n.set_language("it")
    try:
        def italian(dialog):
            assert dialog.buttons["add"].cget("text") == "Aggiungi…"
            assert dialog.tree.item("1")["values"][1] == "Rettangolo"

            def fill(editor):
                box = editor.widgets["kind"]
                assert box.cget("values")[1] == "Rettangolo", box.cget("values")
                box.current(2)
                box.event_generate("<<ComboboxSelected>>")
                layer = editor.widgets["layer"]
                layer.current(0)
                layer.event_generate("<<ComboboxSelected>>")
                editor.fields["line_style"].set("Punteggiata")  # a label written into the canonical variable
                for name, value in zip(("x1", "y1", "x2", "y2"), ("0,05", "0,05", "0,25", "0,3")):
                    editor.fields[name].set(value)
                editor.fields["fill"].set("#fde0c5")
            drive_editor(fill, shot="window-graph-shapes-editor-it.png")
            dialog.add()
            dialog.update()
            capture(dialog, "window-graph-shapes-list-it.png")
            dialog.apply_button.invoke()

        kit.drive_dialog(GraphShapesDialog, italian)
        app.edit_graph_shapes()
        root.update()
    finally:
        i18n.set_language("en")
    run = app.runs[0]
    added = run.style[SHAPES][-1]
    assert (added["kind"], added["layer"], added["line_style"]) == ("ellipse", "below", "dotted"), added
    assert added["points"] == [[.05, .05], [.25, .3]], added
    records = deepcopy(run.style[SHAPES])
    assert len(records) == 4

    # 5. Save, reopen opening the graph before the data, edit a value and recalculate.
    app.path = path
    assert app.save()
    stored = _project_strings(path)
    for label in ("Linea", "Rettangolo", "Ellisse", "Dati (asse Y sinistro)", "Frazioni del grafico (0–1)",
                  "Sotto i dati", "Sopra i dati", "Punteggiata", "Tratteggiata", "Continua", "Tratto-punto"):
        assert label not in stored, f"translated label {label!r} stored in the project"
    assert {"line", "rectangle", "ellipse", "below", "above", "dotted"} <= stored
    app.import_file(path)
    app.open_sheet(("graph", 0))
    wait()
    run = app.runs[0]
    assert run.style[SHAPES] == records and run.style[ANNOTATIONS] == annotation
    assert _shape_ids(run.result.figure) == ["tramastat-shape-" + record["id"] for record in records]
    assert not app.dirty, "opening the project made it dirty"
    app.show("data", TITLE)
    app.edit_cell(1, 1, "4,4")
    wait()
    app.open_sheet(("graph", 0))
    wait()
    run = app.runs[0]
    assert run.style[SHAPES] == records
    assert len(run.result.figure.axes[0]._tramastat_shapes) == 4
    capture(app.root, "window-graph-shapes-reopened.png")

    # 6. Graph exports: PNG size, SVG groups with vector children, PDF paths and searchable text.
    def export(target, fmt, width, text_mode="Text"):
        def act(dialog):
            dialog.format.set(fmt)
            dialog.width.set(width)
            if fmt == "SVG":
                dialog.svg_text.set(text_mode)
        kit.drive_dialog(FigureExportDialog, act)
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)), \
                patch.object(app, "error") as error:
            app.export_with_options()
        assert not error.called, error.call_args
        assert target.exists(), target

    figure = run.result.figure
    # Let the graph page settle first: the Tk canvas sizes the figure to the window, not the export.
    root.update()
    before = (tuple(figure.get_size_inches()), figure.dpi, figure.canvas, figure.axes[0].get_xlim(),
              figure.axes[0].get_ylim())
    export(out / "graph-shapes.svg", "SVG", "120")
    svg = ET.parse(out / "graph-shapes.svg").getroot()
    assert not svg.findall(f".//{SVG}image")
    for record in records:
        group = svg.find(f".//{SVG}g[@id='tramastat-shape-{record['id']}']")
        assert group is not None and list(group.iter(f"{SVG}path")), record["id"]
    assert any(LABEL in "".join(node.itertext()) for node in svg.iter(f"{SVG}text"))
    export(out / "graph-shapes.pdf", "PDF", "120")
    text, paths, images = _pdf_objects(out / "graph-shapes.pdf")
    assert LABEL in text and paths >= 4 and images == 0, (text, paths, images)
    export(out / "graph-shapes.png", "PNG", "120")
    with Image.open(out / "graph-shapes.png") as image:
        assert image.size[0] > 400, image.size
    root.update()
    after = (tuple(figure.get_size_inches()), figure.dpi, figure.canvas, figure.axes[0].get_xlim(),
             figure.axes[0].get_ylim())
    assert before == after and len(figure.axes[0]._tramastat_shapes) == 4, (before, after)

    # 7. A two-panel layout keeps each panel's shapes as vectors with unique ids.
    app.open_sheet(("graph", 1))
    wait()

    def one(dialog):
        drive_editor(rectangle)
        dialog.add()
        dialog.apply_button.invoke()

    kit.drive_dialog(GraphShapesDialog, one)
    app.edit_graph_shapes()
    root.update()
    assert len(app.runs[1].style[SHAPES]) == 1 and len(app.runs[1].result.figure.axes[0]._tramastat_shapes) == 1

    def compose(dialog):
        dialog.name.set("Shapes layout")
        dialog.columns.set("2")
        dialog.list.selection_clear(0, "end")
        for index in range(len(dialog.runs)):
            dialog.list.selection_set(index)
        dialog.add_selected()

    kit.drive_dialog(kit.LayoutDialog, compose)
    app.new_layout()
    root.update()
    layout = len(app.layouts) - 1
    app.show("layout", layout)
    app.recalculate_layout(layout)
    wait()
    app.show("layout", layout)
    root.update()
    capture(app.root, "window-graph-shapes-layout.png")
    export(out / "layout-shapes.svg", "SVG", "160")
    svg = ET.parse(out / "layout-shapes.svg").getroot()
    ids = [item.get("id") for item in svg.iter() if item.get("id")]
    assert len(ids) == len(set(ids)), "duplicate ids in the layout SVG"
    assert not svg.findall(f".//{SVG}image")
    shape_groups = [item for item in svg.iter(f"{SVG}g") if "tramastat-shape-" in (item.get("id") or "")]
    assert len(shape_groups) == 5 and all(list(group.iter(f"{SVG}path")) for group in shape_groups), len(shape_groups)
    export(out / "layout-shapes.pdf", "PDF", "160")
    text, paths, images = _pdf_objects(out / "layout-shapes.pdf")
    assert LABEL in text and paths >= 5 and images == 0, (text, paths, images)
    (out / "evidence.json").write_text(json.dumps({
        "records": records, "annotation": annotation, "layout_shape_groups": len(shape_groups),
        "graph_pdf_paths": _pdf_objects(out / "graph-shapes.pdf")[1], "layout_pdf_paths": paths,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def _project_strings(path):
    """Every string value and key stored in a project file, zipped or plain JSON."""
    raw = path.read_bytes()
    if raw[:2] == b"PK":
        with ZipFile(path) as archive:
            documents = [json.loads(archive.read(name)) for name in archive.namelist() if name.endswith(".json")]
    else:
        documents = [json.loads(raw.decode("utf-8"))]
    found = set()

    def walk(value):
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                found.add(key)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for document in documents:
        walk(document)
    return found
