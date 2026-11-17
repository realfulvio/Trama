"""Desktop smoke for creating, preserving and removing a native graph annotation."""
from unittest.mock import patch

import pandas as pd

from .data import Dataset, save_project
from .figure_export_dialog import FigureExportDialog
from .graph_annotation_dialog import AnnotationEditor, GraphAnnotationsDialog
from .graph_annotations import ANNOTATIONS
from .graph_dialog import GraphFormatDialog


def check_graph_annotations(h):
    app, root = h.app, h.root
    title = "Annotation data"
    path = h.directory / "annotation-graph.alab"
    dataset = Dataset(pd.DataFrame({"Dose": [1., 2., 4., 6.], "Response": [2.1, 3.8, 8.2, 11.7]}))
    dataset.analyses.append(("Linear regression", {"X": "Dose", "Y": "Response"}))
    save_project(path, {title: dataset})
    app.import_file(path)
    app.open_sheet(("graph", 0))
    h.wait_for_calculation()
    label = "Response < 10 – città\nFollow-up"

    def add(dialog):
        def fields(editor):
            editor.text.insert("1.0", label)
            editor.position[0].set("1.2")
            assert not editor.validate() and "between 0 and 1" in editor.problem.cget("text")
            editor.position[0].set("0,12")
            editor.position[1].set("0,85")
            editor.arrow.set(True)
            editor.show_arrow()
            editor.target[0].set("0,57")
            editor.target[1].set("0,63")
            h.capture(editor, "window-graph-annotation-editor.png")

        h.drive_dialog(AnnotationEditor, fields)
        dialog.add()
        assert dialog.tree.get_children() == ("0",), dialog.records
        h.capture(dialog, "window-graph-annotation-list.png")

    h.drive_dialog(GraphAnnotationsDialog, add)
    app.edit_graph_annotations()
    run = app.runs[0]
    record, = run.style[ANNOTATIONS]
    assert record["text"] == label and record["position"] == [.12, .85] and record["target"] == [.57, .63]
    figure = run.result.figure
    assert figure.axes[0]._tramastat_annotations[0].arrow_patch is not None
    h.capture(root, "window-graph-annotation.png")

    # Existing formatting and its Reset action preserve the annotation.
    h.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Annotated regression"))
    app.format_graph()
    assert run.style[ANNOTATIONS] == [record] and run.result.figure.axes[0].get_title() == "Annotated regression"

    def reset():
        dialog = next(child for child in root.winfo_children() if isinstance(child, GraphFormatDialog))
        dialog._reset()

    root.after(200, reset)
    app.format_graph()
    assert run.style == {ANNOTATIONS: [record]}

    def svg(dialog):
        dialog.format.set("SVG")
        dialog.svg_text.set("Text")
        dialog.width.set("120")

    h.drive_dialog(FigureExportDialog, svg)
    target = h.directory / "graph-annotation.svg"
    with patch.object(h.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export_with_options()
    document = target.read_text(encoding="utf-8")
    assert "Response &lt; 10 – città" in document and "Follow-up" in document
    assert app.save()
    app.import_file(path)
    app.open_sheet(("graph", 0))
    h.wait_for_calculation()
    run = app.runs[0]
    assert run.style[ANNOTATIONS] == [record]
    assert run.result.figure.axes[0]._tramastat_annotations[0].get_text() == label
    app.show("data", title)
    app.edit_cell(1, 1, "4.2")
    h.wait_for_calculation()
    app.open_sheet(("graph", 0))
    h.wait_for_calculation()
    assert run.style[ANNOTATIONS] == [record]
    assert run.result.figure.axes[0]._tramastat_annotations[0].get_text() == label

    # Delete in the dialog and cancel, then apply the same removal.
    def remove(dialog):
        dialog.tree.selection_set("0")
        dialog.remove()
        assert dialog.records == []

    def cancel():
        dialog = next(child for child in root.winfo_children() if isinstance(child, GraphAnnotationsDialog))
        remove(dialog)
        dialog.cancel()

    root.after(200, cancel)
    app.edit_graph_annotations()
    assert run.style[ANNOTATIONS] == [record]
    h.drive_dialog(GraphAnnotationsDialog, remove)
    app.edit_graph_annotations()
    assert ANNOTATIONS not in run.style and not run.result.figure.axes[0]._tramastat_annotations
