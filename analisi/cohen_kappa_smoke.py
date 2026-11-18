"""Desktop smoke check for Cohen's kappa, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_cohen_kappa` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=cohen-kappa python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixture (tests/data/cohen_kappa) and a seeded table of scores 1 to 5. The expected
kappas are the frozen fractions of expected.json, never computed by the module under test, except where a step
recalculates the same recipe through the dispatcher to prove that the dialog, the worker and the saved recipe agree.
Every widget is driven through its real handler; the only injected event is Alt+Down on the order list.
"""
from fractions import Fraction
import json
from pathlib import Path
import time
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import cohen_kappa_workbench as kw, i18n
from .cohen_kappa import (BOOTSTRAP, FIRST, INTERVAL, LEVEL, ORDER, RESAMPLES, SECOND, SEED, SHOW_GRAPH,
                          WEIGHTING)
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "cohen_kappa"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = kw.COHEN_KAPPA
RATINGS, SCORES = "Ratings", "Scores"
LEVELS = ["Mild", "Moderate $", "Severe"]
COUNTS = [[8, 2, 1], [1, 7, 2], [0, 3, 6]]
SHEETS = ["Agreement", "Counts", "Expected counts", "Category totals", "Settings"]


def scores_table():
    """Two raters scoring 60 subjects from 1 to 5, mostly within one point; two scores are missing."""
    rng = np.random.default_rng(2093)
    first = rng.integers(1, 6, 60)
    second = np.clip(first + rng.choice([-1, 0, 0, 0, 1], 60), 1, 5)
    frame = pd.DataFrame({"Reader 1": first.astype(float), "Reader 2": second.astype(float)})
    frame.loc[[7, 41], ["Reader 1", "Reader 2"]] = [[np.nan, 3.0], [2.0, np.nan]]
    return frame


def check_cohen_kappa(root, app, directory, tools):
    """Exercise both locales using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_cohen_kappa(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_cohen_kappa(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "cohen-kappa"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    ratings = pd.read_csv(DATA / "ratings.csv")
    scores = scores_table()
    path = directory / "cohen-kappa.alab"
    save_project(path, {RATINGS: Dataset(ratings.copy()), SCORES: Dataset(scores.copy())})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "language": i18n.active_language(), "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        """The notebook page that holds a field (the Ratings page scrolls, so its rows sit one level deeper)."""
        page = dialog.field_rows[field][1].master
        while page.master is not dialog.fields:
            page = page.master
        return str(page)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert (caption or field).lower() in message.lower() and contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), field
        target = dialog.initial_focus
        assert target is not None and target.winfo_exists(), "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def run_button(dialog):
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button) and child.cget("text") == i18n.ui("Run Analysis"):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(dialog)

    def reachable(dialog):
        """Run Analysis and every tab lie inside the screen at the current size."""
        dialog.update()
        button = run_button(dialog)
        assert button is not None and button.winfo_viewable()
        assert button.winfo_rooty() + button.winfo_height() <= screen[1], (button.winfo_rooty(), screen)
        assert button.winfo_rootx() + button.winfo_width() <= screen[0]
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
        dialog.fields.select(0)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def agreement(index):
        return table(index, "Agreement").iloc[0]

    def mesh(index):
        axes = app.runs[index].result.figure.axes[0]
        return axes, next(item for item in axes.collections if item.get_gid() == kw.GID_COUNTS)

    def drawn_as_sheet(index):
        """The drawn matrix is the Counts sheet: values, orientation, labels and the count written in each cell."""
        sheet = table(index, "Counts")
        axes, quad = mesh(index)
        size = len(sheet)
        assert np.array_equal(np.asarray(quad.get_array()).reshape(size, size), sheet.to_numpy())
        assert [t.get_text() for t in axes.get_xticklabels()] == list(sheet.columns)
        assert [t.get_text() for t in axes.get_yticklabels()] == list(sheet.index)
        assert axes.get_ylim() == (size, 0), "the first category is the top row, as in the sheet"
        assert (axes.get_ylabel(), axes.get_xlabel()) == (sheet.index.name, sheet.columns.name)
        written = {text.get_gid(): text.get_text() for text in axes.texts}
        for (row, column), value in np.ndenumerate(sheet.to_numpy()):
            assert written[kw.GID_COUNT.format(row=row + 1, column=column + 1)] == str(value)
        return sheet

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    def edit_with(index, action, initial_field=None):
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.show("result", index)
        app.edit_analysis(initial_field=initial_field)
        wait()

    # 1. English dialog: Quadratic weights without an order are refused on Category order; Propose, Up and Down
    # (also Alt+Down on the list) fix the same field; then the bootstrap with the packaged seed.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Ratings", "Interval and graph"]
        assert (controls[FIRST][1].get(), controls[SECOND][1].get()) == ("Rater A", "Rater B")
        editor = controls[ORDER][1]
        assert editor.observed == LEVELS and editor.values() == [], editor.observed
        assert not placed(dialog, RESAMPLES) and not placed(dialog, SEED) and not placed(dialog, LEVEL)
        controls[WEIGHTING][1].set("Quadratic")
        dialog.update()
        assert "need an order" in editor.note.cget("text"), editor.note.cget("text")
        rejected(dialog, ORDER, "Quadratic weights need an order", "window-cohen-kappa-error.png")
        assert dialog.initial_focus is editor.listbox
        editor.propose()
        assert editor.values() == LEVELS
        editor.listbox.selection_clear(0, "end")
        editor.listbox.selection_set(2)
        editor.move(-1)
        assert editor.values() == ["Mild", "Severe", "Moderate $"]
        editor.listbox.focus_force()
        dialog.update()
        editor.listbox.event_generate("<Alt-Down>", when="now")
        dialog.update()
        assert editor.values() == LEVELS, editor.values()
        controls[INTERVAL][1].set(BOOTSTRAP)
        dialog.update()
        assert placed(dialog, RESAMPLES) and placed(dialog, SEED) and placed(dialog, LEVEL)
        controls[RESAMPLES][1].set("1999")
        controls[SEED][1].set("2701")
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-cohen-kappa-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-cohen-kappa-interval" + suffix + ".png")
        dialog.fields.select(0)

    main = analyse_with(english, RATINGS)
    options = app.runs[main].options
    assert options == {FIRST: "Rater A", SECOND: "Rater B", WEIGHTING: "Quadratic", ORDER: LEVELS,
                       INTERVAL: BOOTSTRAP, LEVEL: 95.0, RESAMPLES: 1999, SEED: 2701, SHOW_GRAPH: True}, options
    assert list(app.runs[main].result.tables) == SHEETS
    row = agreement(main)
    assert row["Kappa"] == float(Fraction(EXPECTED["exact_scores"]["Quadratic"])), row["Kappa"]
    assert (int(row["Complete pairs"]), int(row["Incomplete pairs"])) == (30, 2) and row["Status"] == "OK"
    assert row["CI lower"] < row["Kappa"] < row["CI upper"] and int(row["Valid resamples"]) >= 1800
    assert table(main, "Counts").to_numpy().tolist() == COUNTS
    same = analyse(METHOD, app.tables[RATINGS].frame(mask_excluded=True), dict(options))
    for name in SHEETS:
        pd.testing.assert_frame_equal(table(main, name), same.tables[name])
    done("english dialog: Quadratic without an order refused on Category order, fixed with Propose, Up and Alt+Down")
    done("bootstrap 1999 resamples, seed 2701: kappa 13/19, the worker and the dispatcher agree")

    app.show("result", main)
    app.result_tabs.select(0)
    shot(root, "window-cohen-kappa-results" + suffix + ".png")
    app.result_tabs.select(1)
    root.update()
    shot(root, "window-cohen-kappa-counts" + suffix + ".png")
    app.show("graph", main)
    root.update()
    drawn_as_sheet(main)
    shot(root, "window-cohen-kappa-graph" + suffix + ".png")
    done("graph: the drawn matrix is the Counts sheet with its orientation and labels")

    # 2. Cancel during the bootstrap keeps the last result; a new run gives the same interval.
    app.show("result", main)
    previous = app.runs[main].result
    app.recalculate(main)
    assert app.calculation is not None, "the bootstrap offers Cancel"
    app.calculation.cancel.set()
    wait()
    assert app.runs[main].result is previous, "Cancel keeps the last completed result"
    assert app.status.get() == f"{METHOD} cancelled. The last completed results are kept.", app.status.get()
    app.recalculate(main)
    wait()
    assert app.runs[main].result is not previous and not errors, errors
    pd.testing.assert_frame_equal(table(main, "Agreement"), previous.tables["Agreement"])
    done("Cancel during the bootstrap and a new run with the same interval")

    # 3. Italian dialog on numeric scores: Linear weights need the order, Propose lists 1 to 5.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
        assert captions[ORDER] == "Ordine delle categorie" and captions[FIRST] == "Primo valutatore", captions
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Valutazioni", "Intervallo e grafico"]
        assert list(dialog.field_rows[WEIGHTING][1].cget("values")) == ["Non pesato", "Lineare", "Quadratico"]
        dialog.controls[WEIGHTING][1].set("Linear")
        dialog.update()
        rejected(dialog, ORDER, "con i pesi «Lineare» serve un ordine", "window-cohen-kappa-it-error.png",
                 caption="Ordine delle categorie")
        editor = dialog.controls[ORDER][1]
        editor.propose()
        assert editor.values() == ["1", "2", "3", "4", "5"], editor.values()
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-cohen-kappa-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-cohen-kappa-it-interval" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, SCORES)
        options_it = app.runs[italian_index].options
        assert options_it[WEIGHTING] == "Linear" and options_it[INTERVAL] == "None", options_it
        assert options_it[ORDER] == ["1", "2", "3", "4", "5"], options_it
        row = agreement(italian_index)
        assert (int(row["Complete pairs"]), int(row["Incomplete pairs"])) == (58, 2), row
        app.show("graph", italian_index)
        root.update()
        drawn_as_sheet(italian_index)
        shot(root, "window-cohen-kappa-it-graph" + suffix + ".png")
        app.show("result", italian_index)
        shot(root, "window-cohen-kappa-it-results" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    done("italian dialog: Linear without an order refused on its field, numeric labels 1 to 5, canonical recipe")

    # 4. A new category typed in a cell, then the cell excluded: each time the analysis keeps its last result,
    # reopens on Category order and Propose in the reopened dialog fixes the same field.
    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(root)

    def recover(change, fragment, note, proposed, shot_name):
        kept = app.runs[main].result
        state = {"done": False}

        def recovered(tries=0):
            dialog = find_dialog()
            if dialog is None or not dialog.winfo_viewable():
                if tries > 1200:
                    errors.append("the recovered AnalysisDialog did not open")
                    state["done"] = True
                    return
                root.after(25, lambda: recovered(tries + 1))
                return
            try:
                assert dialog.error_label is not None, "no banner"
                banner = dialog.error_label.cget("text")
                assert banner.startswith("Category order: ") and fragment in banner, banner
                assert dialog.initial_field == ORDER
                assert dialog.fields.select() == page_of(dialog, ORDER)
                editor = dialog.controls[ORDER][1]
                assert note in editor.note.cget("text"), editor.note.cget("text")
                dialog.update()
                shot(dialog, shot_name + suffix + ".png")
                editor.propose()
                assert editor.values() == proposed, editor.values()
                dialog.ok()
            except Exception as error:
                errors.append(repr(error))
                dialog.cancel()
            state["done"] = True

        app.show("data", RATINGS)
        root.after(25, recovered)
        change()
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            time.sleep(.02)
        wait()
        assert not errors, errors
        assert app.runs[main].result is not kept, "the corrected recipe is calculated again"
        assert app.runs[main].calculation_error is None
        assert app.runs[main].options[ORDER] == proposed

    column = app.tables[RATINGS].raw.columns.get_loc("Rater A")
    recover(lambda: app.edit_cell(0, column, "Critical"), 'missing "Critical"', "Not in the order yet: Critical",
            LEVELS + ["Critical"], "window-cohen-kappa-recovered")
    sheet = drawn_as_sheet(main)
    assert list(sheet.index) == LEVELS + ["Critical"] and int(sheet.loc["Critical", "Mild"]) == 1
    assert int(sheet.loc["Mild", "Mild"]) == 7
    done("a new category in a cell reopens Category order; Propose adds it and the matrix grows to 4 × 4")

    def exclude():
        app.current_grid.select((0, column))
        app.toggle_exclusion()

    recover(exclude, '"Critical" is not a category of the complete pairs', "Not in the complete pairs: Critical",
            LEVELS, "window-cohen-kappa-recovered-excluded")
    row = agreement(main)
    assert (int(row["Complete pairs"]), int(row["Incomplete pairs"])) == (29, 3), row
    assert table(main, "Counts").to_numpy().tolist() == [[7, 2, 1], [1, 7, 2], [0, 3, 6]]
    drawn_as_sheet(main)
    done("the excluded cell leaves the pair out; Propose drops the stale category on the same field")

    # A failure the user does not fix: the kept result is flagged stale until the data allow it again.
    app.show("data", RATINGS)
    kept_tables = {name: frame.copy() for name, frame in app.runs[main].result.tables.items()}
    state = {"done": False}

    def dismiss(tries=0):
        dialog = find_dialog()
        if dialog is None or not dialog.winfo_viewable():
            if tries > 1200:
                errors.append("the recovered AnalysisDialog did not open")
                state["done"] = True
                return
            root.after(25, lambda: dismiss(tries + 1))
            return
        dialog.cancel()
        state["done"] = True

    root.after(25, dismiss)
    app.edit_cell(1, column, "Unknown")
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    assert not errors, errors
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[main].result.tables[name], frame)
    assert app.runs[main].calculation_error and "Unknown" in app.runs[main].calculation_error
    app.show("result", main)
    assert app.stale_calculation_note() is not None, "the stale result must be flagged"
    shot(root, "window-cohen-kappa-stale" + suffix + ".png")
    app.show("data", RATINGS)
    app.edit_cell(1, column, "Mild")
    wait()
    assert app.runs[main].calculation_error is None and app.stale_calculation_note(("result", main)) is None
    done("an unfixed category keeps the last result flagged stale; restoring the cell recovers")

    # 5. Graph settings shortcut, Format Graph and the Inspector on the matrix: the result object is unchanged.
    app.show("graph", main)
    root.update()

    def graph_settings(dialog):
        assert dialog.fields.select() == page_of(dialog, SHOW_GRAPH), "Graph settings opens the graph page"
        assert dialog.controls[SHOW_GRAPH][1].get() in (True, 1, "1")

    edit_with(main, graph_settings, SHOW_GRAPH)
    app.show("graph", main)
    root.update()
    before = app.runs[main].result
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Agreement of $raters$ and _text_"))
    app.format_graph()
    wait()
    assert app.runs[main].result is before, "Format Graph restyles the figure without calculating again"
    axes = app.runs[main].result.figure.axes[0]
    assert axes.get_title() == "Agreement of $raters$ and _text_"
    drawn_as_sheet(main)
    app.show("graph", main)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None
    panel.vars["title"].set("Draft title")
    panel._now("title")
    root.update()
    assert app.runs[main].result.figure.axes[0].get_title() == "Draft title"
    panel.cancel()
    root.update()
    assert app.inspector is None
    assert app.runs[main].result.figure.axes[0].get_title() == "Agreement of $raters$ and _text_"
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    panel.vars["title"].set("Rater agreement: $x$ & {y}")
    panel._now("title")
    assert panel.apply(), panel.errors
    assert app.runs[main].style["title"] == "Rater agreement: $x$ & {y}"
    assert app.runs[main].result is before
    shot(root, "window-cohen-kappa-inspector" + suffix + ".png")
    app.toggle_inspector()
    root.update()
    done("Graph settings shortcut, Format Graph and the Inspector keep the result and literal text")

    # 6. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure and a two-panel layout.
    app.show("result", main)
    for position, name in enumerate(SHEETS):
        app.result_tabs.select(position)
        target = out / f"cohen-kappa-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig", keep_default_na=False)
        assert len(exported) >= 1, name
        if name == "Counts":
            assert list(exported.columns) == LEVELS and list(exported.index) == LEVELS, exported
            assert exported.to_numpy().tolist() == table(main, "Counts").to_numpy().tolist()
    app.show("graph", main)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"cohen-kappa.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "cohen-kappa.svg").read_text(encoding="utf-8")
    assert 'id="kappa-counts"' in svg and 'id="kappa-diagonal-3"' in svg and "<image" not in svg
    assert "Moderate $" in svg and "Rater agreement: $x$ &amp; {y}" in svg
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "cohen-kappa.pdf")
    assert "Rater agreement" in pdf_text and "Moderate $" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("Kappa panels", 2, [app.runs[main].reference, app.runs[italian_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    target = exports / "layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    assert target.read_bytes()[:4] == b"%PDF" and target.stat().st_size > 1000
    layout_svg = exports / "layout.svg"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    text = layout_svg.read_text(encoding="utf-8")
    assert "<svg" in text[:600] and "<image" not in text
    shot(root, "window-cohen-kappa-layout" + suffix + ".png")
    done("CSV of every sheet, PNG, SVG, PDF and a two-panel layout in vector formats")

    # 7. Save, reopen with the graph first: canonical recipes, the same tables and the style.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method == METHOD}
    assert len(expected_runs) >= 2, sorted(expected_runs)
    app.path = directory / "cohen-kappa-saved.alab"
    assert app.save()
    (out / "cohen-kappa-synthetic.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD:
            app.open_sheet(("graph", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame)
    key = next(k for k in expected_runs if k[0] == RATINGS)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert reopened[key].style["title"] == "Rater agreement: $x$ & {y}"
    app.show("graph", position)
    root.update()
    assert app.runs[position].result.figure.axes[0].get_title() == "Rater agreement: $x$ & {y}"
    drawn_as_sheet(position)
    shot(root, "window-cohen-kappa-reopened" + suffix + ".png")
    done("save and reopen from the graph: the same recipes, tables, matrix and style")

    # 8. Use Result as Data turns the Counts sheet into a worksheet with the first rating as a column.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(1)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns) == ["Rater A", *LEVELS], list(frame.columns)
    assert frame["Rater A"].tolist() == LEVELS
    assert frame[LEVELS].to_numpy().tolist() == table(position, "Counts").to_numpy().tolist()
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data on the Counts sheet")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
