"""Desktop smoke check for Insert → Pairwise Comparisons…, kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_pairwise_comparisons` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=pairwise python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import pairwise_graph as pg
from .data import Dataset, save_project
from .presentation import Layout, apply_style, compose_layout

TITLE, COLUMNS = "Pairwise groups", "Pairwise columns"
BOX = "Box / violin plot"


def _data():
    values = {"A": [1.0, 1.4, .8, 1.2, 1.1], "B": [1.3, 1.7, 1.0, 1.5, 1.2],
              "C": [2.0, 2.4, 1.9, 2.6, 2.2], "D": [4.1, 4.6, 3.9, 4.4, 4.2]}
    groups = [name for name in values for _ in values[name]]
    return pd.DataFrame({"Group": groups, "Response": [v for name in values for v in values[name]]})


def _labels(figure):
    return [artist.get_text() for artist in figure.artists if str(artist.get_gid()).startswith("pairwise:label")]


def _pairs(figure):
    return [(b["left"].rsplit(":", 1)[1], b["right"].rsplit(":", 1)[1], b["lane"]) for b in pg.drawn_brackets(figure)]


def _adjusted(tables, sheet="Multiple comparisons"):
    frame = tables[sheet]
    return {frozenset((f"category:str:{a}", f"category:str:{b}")): p
            for a, b, p in zip(frame["First"], frame["Second"], frame["Adjusted p"])}


def check_pairwise_comparisons(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, PairwiseDialog, capture, drive_dialog, pick_method,
    select_columns, wait_for_calculation."""
    wait, capture, drive = tools.wait_for_calculation, tools.capture, tools.drive_dialog
    Dialog = tools.PairwiseDialog

    def index_of(method, title=TITLE):
        return next(i for i, run in enumerate(app.runs) if run.method == method and run.title == title)

    def open_pairwise(action, *, cancel=False):
        def enter():
            dialog = next((child for child in root.winfo_children() if isinstance(child, Dialog)), None)
            assert dialog is not None, "Pairwise Comparisons did not open"
            try:
                action(dialog)
            finally:
                (dialog.cancel if cancel else dialog.ok)()

        if cancel:
            root.after(200, enter)
            app.pairwise_comparisons()
        else:
            drive(Dialog, action)
            app.pairwise_comparisons()
        wait()

    path = directory / "pairwise.alab"
    save_project(path, {TITLE: Dataset(_data())})
    app.import_file(path)

    def box(dialog):
        tools.pick_method(dialog, BOX)
        dialog.controls["Response"][1].set("Response")
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Overlay observations"][1].set(True)

    drive(tools.AnalysisDialog, box)
    app.choose_analysis()
    wait()
    graph = index_of(BOX)

    def anova(dialog):
        tools.pick_method(dialog, "One-way ANOVA")
        dialog.controls["Response"][1].set("Response")
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Post-hoc"][1].set("Tukey")

    drive(tools.AnalysisDialog, anova)
    app.choose_analysis()
    wait()
    source = index_of("One-way ANOVA")
    tukey = _adjusted(app.runs[source].result.tables)

    # The legacy graph has no section and no annotation.
    app.show("graph", graph)
    assert pg.SECTION not in app.runs[graph].options and not app.runs[graph].result.figure.artists

    def choose(dialog):
        assert dialog.source.cget("values") and "Tukey" in dialog.source.get(), dialog.source.cget("values")
        assert "adjusted" in dialog.note.cget("text"), dialog.note.cget("text")
        assert len(dialog.tree.get_children()) == 6
        assert all(dialog.tree.set(item, "use") == "☑" for item in dialog.tree.get_children())
        dialog.set_checked([("category:str:A", "category:str:B"), ("category:str:C", "category:str:D"),
                            ("category:str:A", "category:str:D")])
        assert dialog.selection.get() == pg.SELECTED
        dialog.update()
        capture(dialog, "window-pairwise-dialog.png")

    open_pairwise(choose)
    run = app.runs[graph]
    figure = run.result.figure
    assert _pairs(figure) == [("A", "B", 0), ("C", "D", 0), ("A", "D", 1)], _pairs(figure)
    stars = [pg.p_label(tukey[frozenset((f"category:str:{a}", f"category:str:{b}"))], "stars")
             for a, b, _ in _pairs(figure)]
    assert _labels(figure) == stars, (_labels(figure), stars)
    assert "ns" in stars
    # The recipe keeps keys and choices only, never P values.
    assert set(run.options[pg.SECTION]) == pg.FIELDS and run.options[pg.SECTION]["Selection"] == pg.SELECTED
    capture(root, "window-pairwise-stars.png")

    # A cutoff of zero is refused in the dialog; P values at or below .05 are then shown with numbers.
    def numbers(dialog):
        dialog.label.set(pg.P_VALUE)
        dialog.filter.set(pg.AT_OR_BELOW)
        dialog.cutoff.set("0")
        assert dialog.validate() is False and "cutoff" in dialog.problem.cget("text")
        capture(dialog, "window-pairwise-cutoff-error.png")
        dialog.cutoff.set("0,05")
        dialog.color.set("#7a1f5c")

    open_pairwise(numbers)
    figure = app.runs[graph].result.figure
    kept = [pair for pair in _pairs(figure)]
    assert ("A", "B", 0) not in kept and len(kept) == 2, kept
    assert all(text.startswith("p ") for text in _labels(figure)), _labels(figure)
    assert all(artist.get_color() == "#7a1f5c" for artist in figure.artists)
    capture(root, "window-pairwise-pvalues.png")

    # Cancel changes nothing; Remove drops the section; the stored choices come back on the next Apply.
    before = dict(app.runs[graph].options)
    open_pairwise(lambda dialog: dialog.label.set(pg.STARS), cancel=True)
    assert app.runs[graph].options == before
    open_pairwise(lambda dialog: setattr(dialog, "action", "remove"))
    assert pg.SECTION not in app.runs[graph].options and not app.runs[graph].result.figure.artists
    open_pairwise(lambda dialog: (dialog.selection.set(pg.ALL), dialog.label.set(pg.STARS)))
    assert len(pg.drawn_brackets(app.runs[graph].result.figure)) == 6

    # A data edit recalculates the source before the graph; the brackets read the new adjusted P values.
    app.show("data", TITLE)
    app.edit_cell(5, 1, "3.6")
    wait()
    assert app.runs[source].result is not None
    fresh = _adjusted(app.runs[source].result.tables)
    assert fresh != tukey
    rows = app.runs[graph].result.figure.axes[0]._tramastat_pairwise["rows"]
    assert {frozenset((row["left"], row["right"])): row["p"] for row in rows} == fresh

    # Changing the source options from Tukey to Holm updates the labels without the previous result.
    app.show("result", source)

    def holm(dialog):
        dialog.controls["Post-hoc"][1].set("Holm")

    drive(tools.AnalysisDialog, holm)
    app.edit_analysis()
    wait()
    wait()
    holm_p = _adjusted(app.runs[source].result.tables)
    assert app.runs[source].options["Post-hoc"] == "Holm" and holm_p != fresh
    rows = app.runs[graph].result.figure.axes[0]._tramastat_pairwise["rows"]
    assert {frozenset((row["left"], row["right"])): row["p"] for row in rows} == holm_p

    # Hiding D (Inspector visibility) removes its brackets and the lanes close up; showing it restores them.
    app.show("graph", graph)
    run = app.runs[graph]
    hidden = {"groups": {"box:category:str:D": {"visible": False}}}
    apply_style(run.result.figure, hidden)
    app.commit_graph_style(run, hidden)
    app.show("graph", graph)
    assert _pairs(run.result.figure) == [("A", "B", 0), ("B", "C", 1), ("A", "C", 2)], _pairs(run.result.figure)
    capture(root, "window-pairwise-hidden.png")
    apply_style(run.result.figure, {})
    app.commit_graph_style(run, {})
    assert len(pg.drawn_brackets(run.result.figure)) == 6

    # Save and reopen; the graph is opened before its source sheet was ever shown.
    assert app.save()
    app.import_file(path)
    graph, source = index_of(BOX), index_of("One-way ANOVA")
    assert app.runs[source].result is None
    app.open_sheet(("graph", graph))
    wait()
    assert app.runs[source].result is None
    reopened = app.runs[graph].result.figure
    assert len(pg.drawn_brackets(reopened)) == 6 and not pg.pairwise_warning(reopened)

    # Exports keep one copy of each bracket; a layout panel carries them too.
    reopened.savefig(directory / "pairwise-box.svg")
    reopened.savefig(directory / "pairwise-box.png", dpi=100)
    svg = (directory / "pairwise-box.svg").read_text(encoding="utf-8")
    assert all(svg.count(f'id="pairwise:bracket:{n}"') == 1 for n in range(1, 7)), "duplicate brackets"
    assert 'id="pairwise:bracket:7"' not in svg
    layout = compose_layout("Pairwise layout", 1, [reopened])
    layout.savefig(directory / "pairwise-layout.png", dpi=80)
    app.layouts.append(Layout("Pairwise layout", 1, [app.runs[graph].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    capture(root, "window-pairwise-layout.png")

    # FDR is not an accepted source: the graph stays, the brackets go and a message explains why.
    app.show("result", source)
    drive(tools.AnalysisDialog, lambda dialog: dialog.controls["Post-hoc"][1].set(pg.FDR))
    app.edit_analysis()
    wait()
    wait()
    app.show("graph", graph)
    figure = app.runs[graph].result.figure
    assert not pg.drawn_brackets(figure) and "FDR" in pg.pairwise_warning(figure), pg.pairwise_warning(figure)
    assert app.runs[graph].options[pg.SECTION]["Source slot"] == app.runs[source].slot
    capture(root, "window-pairwise-fdr.png")

    # Kruskal–Wallis with Dunn: a second source of the same table, chosen in the dialog.
    def dunn(dialog):
        tools.pick_method(dialog, "Kruskal–Wallis")
        dialog.controls["Response"][1].set("Response")
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Dunn comparisons"][1].set("All pairs")
        dialog.controls["Dunn adjustment"][1].set("Bonferroni")

    app.show("data", TITLE)
    drive(tools.AnalysisDialog, dunn)
    app.choose_analysis()
    wait()
    kruskal = index_of("Kruskal–Wallis")
    app.show("graph", graph)

    def to_dunn(dialog):
        captions = list(dialog.source.cget("values"))
        # The FDR analysis is not offered; the Dunn comparisons are.
        assert len(captions) == 1 and "Dunn" in captions[0], captions
        dialog.source.current(next(i for i, caption in enumerate(captions) if "Dunn" in caption))
        dialog._load()
        assert "adjusted" in dialog.note.cget("text")
        dialog.update()
        capture(dialog, "window-pairwise-dunn-source.png")

    open_pairwise(to_dunn)
    rows = app.runs[graph].result.figure.axes[0]._tramastat_pairwise["rows"]
    assert {frozenset((row["left"], row["right"])): row["p"] for row in rows} == _adjusted(
        app.runs[kruskal].result.tables, "Dunn comparisons")
    capture(root, "window-pairwise-dunn.png")

    # A wide column graph labeled by a paired t-test of two of its columns.
    columns = pd.DataFrame({"Before": [1, 2, 3, 2.5, 5, 4], "After": [3, 5, 4, 6, 8, 6.5],
                            "Reference": [2, 2.5, 3.5, 4, 5.5, 6]})
    save_project(directory / "pairwise-columns.alab", {COLUMNS: Dataset(columns)})
    app.import_file(directory / "pairwise-columns.alab")

    def column_graph(dialog):
        tools.pick_method(dialog, "Column graph")
        tools.select_columns(dialog, "Variables", {"Before", "After", "Reference"})
        dialog.controls["Graph style"][1].set("Bars")
        dialog.controls["Interval"][1].set("SEM")

    drive(tools.AnalysisDialog, column_graph)
    app.choose_analysis()
    wait()
    bars = index_of("Column graph", COLUMNS)

    def paired(dialog):
        tools.pick_method(dialog, "Paired t-test (columns)")
        dialog.controls["First"][1].set("Before")
        dialog.controls["Second"][1].set("After")

    drive(tools.AnalysisDialog, paired)
    app.choose_analysis()
    wait()
    test = index_of("Paired t-test (columns)", COLUMNS)
    p = float(app.runs[test].result.tables["t-test"].at["p", "Value"])
    app.show("graph", bars)

    def column_source(dialog):
        assert len(dialog.tree.get_children()) == 1 and "Before" in dialog.tree.set("0", "pair")
        assert "paired t-test" in dialog.note.cget("text")

    open_pairwise(column_source)
    figure = app.runs[bars].result.figure
    brackets = pg.drawn_brackets(figure)
    assert [(b["left"], b["right"], b["x0"], b["x1"]) for b in brackets] == [("column:Before", "column:After", 0., 1.)]
    assert _labels(figure) == [pg.p_label(p, "stars")]
    capture(root, "window-pairwise-column.png")
    figure.savefig(directory / "pairwise-column.svg")

    # A project saved before this feature, and an external recipe with a broken reference, both open.
    legacy = directory / "pairwise-legacy.alab"
    broken = {"Source slot": 9, "Source method": "One-way ANOVA", "Selection": "All", "Pairs": [],
              "Label": "Stars", "Filter": "All", "Cutoff": .05, "Color": "#303640"}
    graph_options = {"Input": "Single response", "Response": "Response", "Group": "Group", "Style": "Violin"}
    save_project(legacy, {TITLE: Dataset(_data(), analyses=[(BOX, dict(graph_options)),
                                                           (BOX, {**graph_options, pg.SECTION: broken}),
                                                           (BOX, {**graph_options, pg.SECTION: {"Source slot": "x"}})])})
    app.import_file(legacy)
    for index in range(3):
        app.open_sheet(("graph", index))
        wait()
        figure = app.runs[index].result.figure
        assert not figure.artists and figure.axes[0].get_title() == "Violin plot"
    assert pg.pairwise_warning(app.runs[0].result.figure) is None
    assert "no longer" in pg.pairwise_warning(app.runs[1].result.figure)
    assert "not valid" in pg.pairwise_warning(app.runs[2].result.figure)
    assert app.runs[1].options[pg.SECTION] == broken
    np.testing.assert_allclose(app.runs[0].result.figure.axes[0].get_ylim(), app.runs[1].result.figure.axes[0].get_ylim())
    capture(root, "window-pairwise-invalid.png")
    app.show("graph", 0)
    with patch.object(app, "error") as error:
        app.pairwise_comparisons()
    assert "Analyze this table first" in error.call_args.args[0], error.call_args
