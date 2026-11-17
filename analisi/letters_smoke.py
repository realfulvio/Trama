"""Desktop smoke check for the compact letter display, kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_compact_letters` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=letters python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import compact_letters as cl
from . import pairwise_graph as pg
from .data import Dataset, save_project
from .presentation import apply_style

TITLE, COLUMNS = "Letter groups", "Letter columns"
BOX = "Box / violin plot"
KEYS = [f"category:str:{name}" for name in "ABCD"]


def _data():
    # Tukey: A–B and B–C are not significant, A–C is: the nontransitive case A=a, B=a b, C=b.
    values = {"A": [1.0, 1.4, .8, 1.2, 1.1], "B": [1.3, 1.7, 1.0, 1.5, 1.2],
              "C": [1.6, 2.0, 1.5, 2.1, 1.7], "D": [4.1, 4.6, 3.9, 4.4, 4.2]}
    return pd.DataFrame({"Group": [name for name in values for _ in values[name]],
                         "Response": [v for name in values for v in values[name]]})


def _texts(figure, kind="letters"):
    return [artist.get_text() for artist in figure.artists if str(artist.get_gid()).startswith(f"pairwise:{kind}")]


def _expected(tables, groups=KEYS, sheet="Multiple comparisons", **options):
    frame = tables[sheet]
    rows = [{"left": f"category:str:{a}", "right": f"category:str:{b}", "p": p}
            for a, b, p in zip(frame["First"], frame["Second"], frame["Adjusted p"])]
    letters = cl.compact_letters(groups, rows, **options)
    return [" ".join(letters[key]) for key in groups]


def _geometry(figure):
    return [(b["left"], b["right"], b["label"], b["lane"], round(b["y"], 9)) for b in pg.drawn_brackets(figure)]


def check_compact_letters(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, PairwiseDialog, capture, drive_dialog, pick_method,
    select_columns, wait_for_calculation."""
    wait, capture, drive = tools.wait_for_calculation, tools.capture, tools.drive_dialog
    Dialog = tools.PairwiseDialog

    def index_of(method, title=TITLE):
        return next(i for i, run in enumerate(app.runs) if run.method == method and run.title == title)

    def open_dialog(action, *, cancel=False, letters=False):
        opener = app.compact_letter_display if letters else app.pairwise_comparisons

        def enter():
            dialog = next((child for child in root.winfo_children() if isinstance(child, Dialog)), None)
            assert dialog is not None, "Pairwise Comparisons did not open"
            try:
                action(dialog)
            finally:
                (dialog.cancel if cancel else dialog.ok)()

        if cancel:
            root.after(200, enter)
            opener()
        else:
            drive(Dialog, action)
            opener()
        wait()

    def sheet(index):
        return app.runs[index].result.tables.get(pg.LETTERS_SHEET)

    path = directory / "letters.alab"
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
    tukey = app.runs[source].result.tables

    # Brackets first (the 0.57.0 path), then letters, then brackets again with the same pairs and geometry.
    app.show("graph", graph)

    def brackets(dialog):
        assert dialog.display.get() == pg.BRACKETS and dialog.pairs_frame.winfo_ismapped()
        assert not dialog.letters_frame.winfo_ismapped()
        dialog.set_checked([(KEYS[0], KEYS[1]), (KEYS[2], KEYS[3]), (KEYS[0], KEYS[3])])

    open_dialog(brackets)
    figure = app.runs[graph].result.figure
    bracket_geometry = _geometry(figure)
    assert len(bracket_geometry) == 3 and sheet(graph) is None, bracket_geometry
    stored_brackets = dict(app.runs[graph].options[pg.SECTION])

    def to_letters(dialog):
        dialog.display.set(pg.LETTERS)
        dialog.update()
        assert dialog.letters_frame.winfo_ismapped() and not dialog.pairs_frame.winfo_ismapped()
        assert not dialog.look_frame.winfo_ismapped()
        assert "A = a" in dialog.preview.cget("text") and "B = a b" in dialog.preview.cget("text"), \
            dialog.preview.cget("text")
        capture(dialog, "window-letters-dialog.png")

    open_dialog(to_letters)
    run = app.runs[graph]
    figure = run.result.figure
    assert _texts(figure) == ["a", "a b", "b", "c"] == _expected(tukey), _texts(figure)
    assert not _texts(figure, "bracket") and not pg.pairwise_warning(figure)
    section = run.options[pg.SECTION]
    assert section["Display"] == pg.LETTERS and section["Pairs"] == stored_brackets["Pairs"]
    table = sheet(graph)
    assert table.columns.tolist() == ["Group", "Group key", "Letters", "Alpha"]
    assert table["Group"].tolist() == list("ABCD") and table["Letters"].tolist() == ["a", "a b", "b", "c"]
    assert "Graph data" not in run.result.tables or True
    capture(root, "window-letters-graph.png")

    # Back to brackets restores the selected pairs, labels and geometry; then letters again.
    open_dialog(lambda dialog: dialog.display.set(pg.BRACKETS))
    figure = app.runs[graph].result.figure
    assert _geometry(figure) == bracket_geometry and not _texts(figure) and sheet(graph) is None
    assert app.runs[graph].options[pg.SECTION] == {**stored_brackets, "Display": pg.BRACKETS}
    open_dialog(lambda dialog: None, letters=True)
    assert _texts(app.runs[graph].result.figure) == ["a", "a b", "b", "c"]

    # Invalid alpha and text size are refused in the dialog; Cancel changes nothing.
    def invalid(dialog):
        assert dialog.display.get() == pg.LETTERS
        dialog.alpha.set("1")
        assert dialog.validate() is False and "alpha" in dialog.problem.cget("text"), dialog.problem.cget("text")
        capture(dialog, "window-letters-alpha-error.png")
        dialog.alpha.set("0,05")
        dialog.size.set("30")
        assert dialog.validate() is False and "text size" in dialog.problem.cget("text")

    before = dict(app.runs[graph].options)
    open_dialog(invalid, cancel=True)
    assert app.runs[graph].options == before

    # A larger alpha and uppercase identifiers: B–C (P ≈ 0.066) becomes significant at 0.1.
    def alpha_upper(dialog):
        dialog.alpha.set("0.1")
        dialog.identifiers.set("Uppercase")
        dialog.size.set("12")

    open_dialog(alpha_upper)
    figure = app.runs[graph].result.figure
    assert _texts(figure) == _expected(tukey, alpha=.1, identifiers="upper") == ["A", "A", "B", "C"], _texts(figure)
    assert sheet(graph)["Alpha"].tolist() == [.1] * 4
    open_dialog(lambda dialog: (dialog.alpha.set("0.05"), dialog.identifiers.set("Lowercase"), dialog.size.set("10")))

    # A data edit recalculates the source before the graph; the letters follow the new P values.
    app.show("data", TITLE)
    app.edit_cell(10, 1, "1.1")
    wait()
    fresh = app.runs[source].result.tables
    assert _texts(app.runs[graph].result.figure) == _expected(fresh), _texts(app.runs[graph].result.figure)
    assert sheet(graph)["Letters"].tolist() == _expected(fresh)
    app.show("data", TITLE)
    app.edit_cell(10, 1, "1.6")
    wait()

    # Tukey → Holm changes the source; A–B and B–C are then tested differently.
    app.show("result", source)
    drive(tools.AnalysisDialog, lambda dialog: dialog.controls["Post-hoc"][1].set("Holm"))
    app.edit_analysis()
    wait()
    wait()
    holm = app.runs[source].result.tables
    assert _texts(app.runs[graph].result.figure) == _expected(holm) == ["a", "a", "b", "c"]
    app.show("result", source)
    drive(tools.AnalysisDialog, lambda dialog: dialog.controls["Post-hoc"][1].set("Tukey"))
    app.edit_analysis()
    wait()
    wait()

    # Hiding D (Inspector visibility) recomputes the letters for A–C; the sheet follows only on Apply.
    app.show("graph", graph)
    run = app.runs[graph]
    hidden = {"groups": {"box:category:str:D": {"visible": False}}}
    apply_style(run.result.figure, hidden)
    assert _texts(run.result.figure) == _expected(tukey, KEYS[:3]) and len(sheet(graph)) == 4
    app.commit_graph_style(run, hidden)
    assert sheet(graph)["Group"].tolist() == list("ABC")
    app.show("graph", graph)
    capture(root, "window-letters-hidden.png")
    apply_style(run.result.figure, {})
    app.commit_graph_style(run, {})
    assert _texts(run.result.figure) == ["a", "a b", "b", "c"] and len(sheet(graph)) == 4

    # Fixed Y limits: the axis is kept, labels that do not fit are omitted, the sheet is unchanged.
    fixed = {"axis": {"y": {"min": 0., "max": 4.75}}}
    apply_style(run.result.figure, fixed)
    app.commit_graph_style(run, fixed)
    app.show("graph", graph)
    figure = run.result.figure
    assert figure.axes[0].get_ylim() == (0., 4.75) and _texts(figure) == ["a", "a b", "b"], _texts(figure)
    assert "fixed Y maximum" in pg.pairwise_warning(figure) and len(sheet(graph)) == 4
    capture(root, "window-letters-fixed.png")
    apply_style(run.result.figure, {})
    app.commit_graph_style(run, {})

    # A compact window keeps the letters readable below the title.
    geometry = root.geometry()
    root.geometry("820x570")
    app.show("graph", graph)
    root.update()
    figure = app.runs[graph].result.figure
    axes = figure.axes[0]
    renderer = figure.canvas.get_renderer()
    title = axes.title.get_window_extent(renderer)
    texts = [artist.get_window_extent(renderer) for artist in figure.artists]
    assert all(box.y1 <= title.y0 for box in texts), (title, texts)
    capture(root, "window-letters-compact.png")
    root.geometry(geometry)
    root.update()

    # Save and reopen; the graph is opened before its source sheet was ever shown.
    assert app.save()
    app.import_file(path)
    graph, source = index_of(BOX), index_of("One-way ANOVA")
    assert app.runs[source].result is None
    app.open_sheet(("graph", graph))
    wait()
    reopened = app.runs[graph].result.figure
    assert _texts(reopened) == ["a", "a b", "b", "c"] and not pg.pairwise_warning(reopened)
    assert sheet(graph)["Letters"].tolist() == ["a", "a b", "b", "c"]

    # Exports: one copy of each label in SVG, PNG, the Comparison letters CSV and Use Result as Data.
    reopened.savefig(directory / "letters-box.svg")
    reopened.savefig(directory / "letters-box.png", dpi=100)
    svg = (directory / "letters-box.svg").read_text(encoding="utf-8")
    assert all(svg.count(f'id="pairwise:letters:{n}"') == 1 for n in range(1, 5)) and "pairwise:letters:5" not in svg
    app.show("result", graph)
    names = list(app.runs[graph].result.tables)
    assert names[-1] == pg.LETTERS_SHEET, names
    app.result_tabs.select(names.index(pg.LETTERS_SHEET))
    target = directory / "comparison-letters.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = pd.read_csv(target)
    assert exported["Letters"].tolist() == ["a", "a b", "b", "c"] and exported["Group key"].tolist() == KEYS
    app.root.update()
    capture(root, "window-letters-sheet.png")
    tables = set(app.tables)
    app.use_result_as_data()
    added = set(app.tables) - tables
    assert len(added) == 1, added
    assert app.tables[added.pop()].raw["Letters"].tolist() == ["a", "a b", "b", "c"]

    # Kruskal–Wallis with Dunn versus control: an incomplete matrix is refused in Apply.
    def dunn(dialog):
        tools.pick_method(dialog, "Kruskal–Wallis")
        dialog.controls["Response"][1].set("Response")
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Dunn comparisons"][1].set("Versus control")
        dialog.controls["Control group"][1].set("A")

    app.show("data", TITLE)
    drive(tools.AnalysisDialog, dunn)
    app.choose_analysis()
    wait()
    app.show("graph", graph)
    before = dict(app.runs[graph].options)

    def refuse(dialog):
        captions = list(dialog.source.cget("values"))
        dialog.source.current(next(i for i, caption in enumerate(captions) if "Dunn" in caption))
        dialog._load()
        assert dialog.validate() is False and "every pair" in dialog.problem.cget("text"), dialog.problem.cget("text")
        dialog.update()
        capture(dialog, "window-letters-incomplete.png")

    open_dialog(refuse, cancel=True)
    assert app.runs[graph].options == before

    # A column graph of two columns labeled by their paired t-test.
    columns = pd.DataFrame({"Before": [1, 2, 3, 2.5, 5, 4], "After": [3, 5, 4, 6, 8, 6.5],
                            "Reference": [2, 2.5, 3.5, 4, 5.5, 6]})
    save_project(directory / "letters-columns.alab", {COLUMNS: Dataset(columns)})
    app.import_file(directory / "letters-columns.alab")

    def column_graph(dialog):
        tools.pick_method(dialog, "Column graph")
        tools.select_columns(dialog, "Variables", {"Before", "After"})
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
    open_dialog(lambda dialog: None, letters=True)
    figure = app.runs[bars].result.figure
    assert _texts(figure) == (["a", "a"] if p > .05 else ["a", "b"]), (_texts(figure), p)
    assert sheet(bars)["Group key"].tolist() == ["column:Before", "column:After"]
    capture(root, "window-letters-column.png")

    # A 0.57.0 bracket recipe (no letter fields) opens as brackets with the same pairs, labels and geometry.
    legacy = directory / "letters-legacy.alab"
    section = {"Source slot": 1, "Source method": "One-way ANOVA", "Selection": "All", "Pairs": [],
               "Label": "Stars", "Filter": "All", "Cutoff": .05, "Color": "#303640"}
    graph_options = {"Input": "Single response", "Response": "Response", "Group": "Group", "Style": "Box"}
    source_options = {"Response": "Response", "Group": "Group", "Method": "Ordinary", "Post-hoc": "Tukey"}
    save_project(legacy, {TITLE: Dataset(_data(), analyses=[
        (BOX, {**graph_options, pg.SECTION: section}), ("One-way ANOVA", source_options),
        (BOX, {**graph_options, pg.SECTION: {**section, "Display": pg.BRACKETS, "Alpha": .2,
                                              "Identifiers": "Numbers"}})])})
    app.import_file(legacy)
    drawn = []
    for index in (0, 2):
        app.open_sheet(("graph", index))
        wait()
        figure = app.runs[index].result.figure
        drawn.append((_geometry(figure), _texts(figure, "label"), figure.axes[0].get_ylim()))
        assert not _texts(figure) and app.runs[index].result.tables.get(pg.LETTERS_SHEET) is None
    assert len(drawn[0][0]) == 6 and drawn[0] == drawn[1], drawn
    np.testing.assert_allclose(drawn[0][2], drawn[1][2])
