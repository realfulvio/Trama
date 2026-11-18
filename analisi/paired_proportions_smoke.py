"""Desktop smoke check for Paired proportions, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_paired_proportions` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=paired-proportions python tramastat.py --smoke DIR``.

Synthetic data only: the frozen fixtures in tests/data/paired_proportions. Expected values are the frozen numbers of
the independent oracle (tests/paired_proportions_oracle.py), not computed by the module under test.
"""
import importlib.util
import json
import math
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .paired_proportions import PAIRED_PROPORTIONS

TESTS = Path(__file__).resolve().parent.parent / "tests"
FIXTURES = TESTS / "data" / "paired_proportions"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
EXACT = "Exact"
OBSERVED, CODES, MATRIX, FLIPPED, GAINS, CONCORDANT = (
    "Paired observations", "Paired typo", "Paired matrix", "Reversed matrix", "Gains only", "Concordant only")
REPORT = ["N pairs", "Before positive fraction", "After positive fraction", "Difference (after − before)",
          "Discordant pairs", "Chi-square", "p", "Matched odds ratio", "OR CI lower", "OR CI upper"]


def matrix(counts):
    a, b, c, d = counts
    return pd.DataFrame({"Row": ["Before negative", "Before positive"], "After negative": [a, c],
                         "After positive": [b, d]})


def worksheets():
    """The packaged observations (two pairs incomplete), a copy with an unknown After code and the 2 × 2 sheets."""
    observed = pd.read_csv(FIXTURES / "observations.csv", keep_default_na=False).astype(object)
    observed = observed.mask(observed == "", None)
    typo = pd.DataFrame({"Before": observed["Before"], "After": observed["After"]}, dtype=object)
    typo.loc[3, "After"] = "pending"
    typo["After checked"] = observed["After"]
    return {OBSERVED: observed, CODES: typo, MATRIX: matrix([4, 9, 2, 2]), FLIPPED: matrix([4, 2, 9, 2]),
            GAINS: matrix([4, 6, 0, 2]), CONCORDANT: matrix([4, 0, 0, 5])}


def load_oracle():
    """The independent oracle (it imports no Trama module), loaded by path because tests/ is not a package."""
    spec = importlib.util.spec_from_file_location("paired_proportions_oracle", TESTS / "paired_proportions_oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def same(actual, expected, label):
    if expected is None:
        assert actual is None or (isinstance(actual, float) and math.isnan(actual)), (label, actual)
    elif expected == "+inf":
        assert actual == math.inf, (label, actual)
    else:
        assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-11), (label, actual, expected)


def check_paired_proportions(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, GraphFormatDialog, LayoutDialog, capture, drive_dialog,
    pick_method, wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "paired-proportions"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    path = directory / "paired-proportions.alab"
    save_project(path, {name: Dataset(frame.copy()) for name, frame in worksheets().items()})
    app.import_file(path)
    original_language = i18n.active_language()
    oracle = load_oracle()

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
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

    def table(index, name):
        return app.runs[index].result.tables[name]

    def report(index):
        return table(index, "Paired proportions")["Value"]

    def counts(index):
        return table(index, "Paired counts").to_numpy().ravel().tolist()

    def assert_expected(index, name):
        values = report(index)
        for field in REPORT:
            same(values[field], EXPECTED[name][field], (name, field))

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == PAIRED_PROPORTIONS and app.runs[index].title == title
        return index

    # 1. Count matrix: defaults, the orientation note, hidden fields, every invalid value on its own field.
    def matrix_dialog(dialog):
        tools.pick_method(dialog, PAIRED_PROPORTIONS)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Data", "Test and graph"]
        assert controls["Input format"][1].get() == "Observations" and controls["Test"][1].get() == "Exact"
        assert controls["Confidence level (%)"][1].get() == "95.0" and controls["Graph"][1].get() is False
        assert controls["Negative value"][1].get() == "0" and controls["Positive value"][1].get() == "1"
        assert all(placed(dialog, name) for name in ("Before", "After", "Negative value", "Positive value"))
        assert not placed(dialog, "After negative counts") and not placed(dialog, "After positive counts")
        controls["Input format"][1].set("Count matrix")
        dialog.update()
        assert placed(dialog, "After negative counts") and placed(dialog, "After positive counts")
        assert not placed(dialog, "Before") and not placed(dialog, "Negative value")
        notes = [label.cget("text") for label in dialog.paired_notes.values() if label.winfo_manager()]
        assert len(notes) == 1 and "Row 1 is Before negative" in notes[0], notes
        controls["After negative counts"][1].set("After negative")
        controls["After positive counts"][1].set("After negative")
        rejected(dialog, "After positive counts", "different columns")
        controls["After positive counts"][1].set("After positive")
        controls["Confidence level (%)"][1].set("100")
        rejected(dialog, "Confidence level (%)", "less than 100", "window-paired-error.png")
        controls["Confidence level (%)"][1].set("abc")
        rejected(dialog, "Confidence level (%)", "must be a number")
        controls["Confidence level (%)"][1].set("95,0")        # a decimal comma is accepted
        reachable(dialog)
        dialog.fields.select(0)
        shot(dialog, "window-paired-matrix-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-paired-options" + suffix + ".png")
        dialog.fields.select(0)

    matrix_index = analyse_with(matrix_dialog, MATRIX)
    assert app.runs[matrix_index].options == {
        "Input format": "Count matrix", "After negative counts": "After negative",
        "After positive counts": "After positive", "Test": "Exact", "Confidence level (%)": 95.0,
        "Graph": False}, app.runs[matrix_index].options
    assert_expected(matrix_index, "direction")
    assert counts(matrix_index) == [4, 9, 2, 2] and "Pairs" not in app.runs[matrix_index].result.tables
    assert list(table(matrix_index, "Paired counts").index) == ["Before negative", "Before positive"]
    assert app.runs[matrix_index].result.figure is None
    app.show("result", matrix_index)
    app.result_tabs.select(1)
    shot(root, "window-paired-report" + suffix + ".png")
    app.result_tabs.select(0)
    shot(root, "window-paired-counts" + suffix + ".png")

    # 2. Observations with the packaged file: errors stay in the dialog, the corrected values run in the same dialog.
    def observations_dialog(dialog):
        tools.pick_method(dialog, PAIRED_PROPORTIONS)
        controls = dialog.controls
        assert controls["Before"][1].get() == "Before" and controls["After"][1].get() == "After"
        message = rejected(dialog, "Before", "off")                 # the default codes are 0 and 1
        assert "source row 1" in message and '"0"' in message and '"1"' in message, message
        controls["Negative value"][1].set("off")
        controls["Positive value"][1].set("off")
        rejected(dialog, "Positive value", "must be different")
        controls["Positive value"][1].set(" ")
        rejected(dialog, "Positive value", "Enter a code")
        controls["Positive value"][1].set("on")
        controls["After"][1].set("Before")
        rejected(dialog, "After", "different columns")
        controls["After"][1].set("After")
        controls["Graph"][1].set(True)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-paired-observations-dialog" + suffix + ".png")

    observed_index = analyse_with(observations_dialog, OBSERVED)
    assert app.runs[observed_index].options == {
        "Input format": "Observations", "Before": "Before", "After": "After", "Negative value": "off",
        "Positive value": "on", "Test": "Exact", "Confidence level (%)": 95.0, "Graph": True}, app.runs[
            observed_index].options
    assert_expected(observed_index, "direction")
    assert counts(observed_index) == [4, 9, 2, 2]
    pairs = table(observed_index, "Pairs")
    assert pairs["Source row"].tolist() == list(range(1, 17)) + [18], pairs["Source row"].tolist()
    assert pairs["Transition"].tolist() == (["Unchanged negative"] * 4 + ["Gain"] * 9 + ["Loss"] * 2
                                            + ["Unchanged positive"] * 2)
    assert report(observed_index)["Discarded pairs"] == 2
    app.show("result", observed_index)
    app.result_tabs.select(2)
    shot(root, "window-paired-pairs" + suffix + ".png")
    app.show("graph", observed_index)
    root.update()
    axes = app.runs[observed_index].result.figure.axes[0]
    assert [patch.get_height() for patch in axes.patches] == [4, 9, 2, 2]
    assert [tick.get_text() for tick in axes.get_xticklabels()] == [
        "Unchanged negative", "Gain", "Loss", "Unchanged positive"]
    shot(root, "window-paired-transitions" + suffix + ".png")

    # 3. The same counts typed into a sheet agree with Observations; exchanging the orientation reverses the result.
    for field in REPORT:
        assert report(matrix_index)[field] == report(observed_index)[field] or (
            field == "Chi-square" and pd.isna(report(matrix_index)[field])), field

    def flipped_dialog(dialog):
        tools.pick_method(dialog, PAIRED_PROPORTIONS)
        dialog.controls["Input format"][1].set("Count matrix")
        dialog.controls["After negative counts"][1].set("After negative")
        dialog.controls["After positive counts"][1].set("After positive")

    flipped_index = analyse_with(flipped_dialog, FLIPPED)
    assert_expected(flipped_index, "reversed")
    assert report(flipped_index)["p"] == report(matrix_index)["p"]
    assert math.isclose(report(flipped_index)["Matched odds ratio"], 1 / report(matrix_index)["Matched odds ratio"])
    assert report(flipped_index)["Difference (after − before)"] == -report(matrix_index)["Difference (after − before)"]

    # 4. Mid-p at 90% and the continuity-corrected chi-square on the same matrix.
    def tests_dialog(test, level, graph=False):
        def action(dialog):
            tools.pick_method(dialog, PAIRED_PROPORTIONS)
            controls = dialog.controls
            controls["Input format"][1].set("Count matrix")
            controls["After negative counts"][1].set("After negative")
            controls["After positive counts"][1].set("After positive")
            controls["Test"][1].set(test)
            controls["Confidence level (%)"][1].set(level)
            controls["Graph"][1].set(graph)
        return action

    mid_index = analyse_with(tests_dialog("Mid-p", "90", graph=True), MATRIX)
    assert_expected(mid_index, "mid")
    chi_index = analyse_with(tests_dialog("Chi-square with continuity correction", "95"), MATRIX)
    assert_expected(chi_index, "continuity")
    assert report(chi_index)["Test"] == "Chi-square with continuity correction"

    # 5. One direction only (infinite odds ratio, still a number in memory) and no discordant pair at all.
    gains_index = analyse_with(tests_dialog("Exact", "95"), GAINS)
    assert_expected(gains_index, "one-way-gains")
    assert report(gains_index)["Matched odds ratio"] == math.inf and "infinite" in report(gains_index)["Note"]
    app.show("result", gains_index)
    app.result_tabs.select(1)
    shot(root, "window-paired-infinite" + suffix + ".png")
    none_index = analyse_with(tests_dialog("Exact", "95"), CONCORDANT)
    assert_expected(none_index, "no-discordance")
    assert "No discordant pairs" in report(none_index)["Note"] and report(none_index)["p"] == 1.0
    app.show("result", none_index)
    app.result_tabs.select(1)
    shot(root, "window-paired-no-discordance" + suffix + ".png")

    # 6. An unknown code in a complete pair names the column and the source row; another column fixes it in the dialog.
    def typo_dialog(dialog):
        tools.pick_method(dialog, PAIRED_PROPORTIONS)
        controls = dialog.controls
        controls["Negative value"][1].set("off")
        controls["Positive value"][1].set("on")
        assert controls["After"][1].get() == "After"
        message = rejected(dialog, "After", "pending")
        assert "source row 4" in message and '"off"' in message and '"on"' in message, message
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-paired-unknown-code" + suffix + ".png")
        controls["After"][1].set("After checked")

    typo_index = analyse_with(typo_dialog, CODES)
    assert app.runs[typo_index].options["After"] == "After checked"
    assert_expected(typo_index, "direction")

    # 7. Excluding a cell discards that pair as a whole, Source row keeps the position in the sheet, and restoring
    # the cell brings the original result back.
    def count_with(counts, level=95.0, test=EXACT):
        return oracle.reference(counts, level, test)

    app.show("data", OBSERVED)
    app.current_grid.select((5, 1))                                  # the After cell of source row 6, a gain
    app.toggle_exclusion()
    wait()
    assert counts(observed_index) == [4, 8, 2, 2], counts(observed_index)
    assert 6 not in table(observed_index, "Pairs")["Source row"].tolist() and report(observed_index)["Discarded pairs"] == 3
    expected = count_with([4, 8, 2, 2])
    for field in REPORT:
        same(report(observed_index)[field], expected[field], ("excluded", field))
    assert [patch.get_height() for patch in app.runs[observed_index].result.figure.axes[0].patches] == [4, 8, 2, 2]
    app.show("data", OBSERVED)
    app.current_grid.select((5, 1))
    app.toggle_exclusion()
    wait()
    assert counts(observed_index) == [4, 9, 2, 2] and report(observed_index)["Discarded pairs"] == 2
    assert_expected(observed_index, "direction")

    # An edit the engine refuses (equal codes) keeps the previous valid result, in the dialog and in the run.
    before = app.runs[observed_index].result

    def bad_edit(dialog):
        dialog.controls["Positive value"][1].set("off")
        rejected(dialog, "Positive value", "must be different")
        dialog.controls["Positive value"][1].set("on")
        dialog.cancel()
        dialog.ok = lambda *args: None

    app.show("result", observed_index)
    tools.drive_dialog(tools.AnalysisDialog, bad_edit)
    app.edit_analysis()
    wait()
    assert app.runs[observed_index].result is before and app.runs[observed_index].options["Positive value"] == "on"

    # 8. Italian dialog: captions, choices, errors and the orientation note; the recipe keeps the English values.
    chi_recipe = {"Input format": "Count matrix", "After negative counts": "After negative",
                  "After positive counts": "After positive", "Test": "Chi-square with continuity correction",
                  "Confidence level (%)": 95.0, "Graph": False}

    def italian(dialog):
        tools.pick_method(dialog, PAIRED_PROPORTIONS)
        captions = {name: dialog.field_rows[name][0].cget("text")
                    for name in ("Input format", "Before", "After", "Negative value", "Positive value", "Test",
                                 "Confidence level (%)", "Graph")}
        assert captions == {"Input format": "Formato dei dati", "Before": "Prima", "After": "Dopo",
                            "Negative value": "Valore negativo", "Positive value": "Valore positivo",
                            "Test": "Test", "Confidence level (%)": "Livello di confidenza (%)",
                            "Graph": "Grafico"}, captions
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Dati", "Test e grafico"]
        form = dialog.field_rows["Input format"][1]
        assert list(form.cget("values")) == ["Osservazioni", "Matrice dei conteggi"], form.cget("values")
        assert dialog.controls["Input format"][1].get() == "Observations" and form.get() == "Osservazioni"
        rejected(dialog, "Before", "riga origine 1", caption="La colonna")   # the codes 0 and 1 match no cell
        dialog.controls["Positive value"][1].set(" ")
        rejected(dialog, "Positive value", "Inserisci un codice per Valore positivo", caption="Valore positivo")
        dialog.controls["Positive value"][1].set("1")
        form.set("Matrice dei conteggi")
        dialog.update()
        assert dialog.controls["Input format"][1].get() == "Count matrix"
        assert placed(dialog, "After negative counts") and not placed(dialog, "Before")
        notes = [label.cget("text") for label in dialog.paired_notes.values() if label.winfo_manager()]
        assert len(notes) == 1 and "La riga 1 è Prima negativo" in notes[0], notes
        dialog.controls["After negative counts"][1].set("After negative")
        dialog.controls["After positive counts"][1].set("After positive")
        test = dialog.field_rows["Test"][1]
        assert list(test.cget("values")) == ["Esatto", "Mid-p", "Chi-quadro con correzione di continuità"]
        dialog.controls["Confidence level (%)"][1].set("100")
        rejected(dialog, "Confidence level (%)", "minore di 100", "window-paired-it-error.png",
                 caption="livello di confidenza")
        dialog.controls["Confidence level (%)"][1].set("95")
        test.set("Chi-quadro con correzione di continuità")
        dialog.update()
        assert dialog.controls["Test"][1].get() == "Chi-square with continuity correction"
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-paired-it" + suffix + ".png")

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, MATRIX)
        assert app.runs[italian_index].options == chi_recipe, app.runs[italian_index].options
        assert_expected(italian_index, "continuity")
        app.show("result", italian_index)
        app.result_tabs.select(1)
        shot(root, "window-paired-it-report" + suffix + ".png")
        i18n.set_language("en")

        def english_again(dialog):
            assert dialog.field_rows["Input format"][1].get() == "Count matrix"
            assert dialog.field_rows["Test"][1].get() == "Chi-square with continuity correction"
            assert dialog.field_rows["Test"][0].cget("text") == "Test"
            assert dialog.field_rows["After negative counts"][0].cget("text") == "After negative counts"

        app.show("result", italian_index)
        tools.drive_dialog(tools.AnalysisDialog, english_again)
        app.edit_analysis()
        wait()
        assert app.runs[italian_index].options == chi_recipe
    finally:
        i18n.set_language(original_language)

    # 9. Inspector and Format Graph on the four-bar figure.
    app.show("graph", observed_index)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn bars"
    panel.select_group(panel.elements[0]["key"])
    panel.vars["element:color"].set("#9b4174")
    widget = panel.fields["color"]["widget"]
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert "#9b4174" in str(app.runs[observed_index].style), app.runs[observed_index].style
    app.toggle_inspector()
    root.update()
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Gains and losses"))
    app.format_graph()
    wait()
    assert app.runs[observed_index].result.figure.axes[0].get_title() == "Gains and losses"
    app.show("graph", observed_index)
    root.update()
    shot(root, "window-paired-graph-formatted" + suffix + ".png")

    # 10. A two-panel layout (observations and mid-p) and the exports of the figure and of the layout.
    def compose(dialog):
        dialog.name.set("Paired layout")
        dialog.columns.set("2")
        dialog.list.selection_clear(0, "end")
        for index in range(len(dialog.runs)):
            dialog.list.selection_set(index)
        dialog.add_selected()

    tools.drive_dialog(tools.LayoutDialog, compose)
    app.new_layout()
    root.update()
    layout = len(app.layouts) - 1
    assert len(app.layouts[layout].panels) == 2, app.layouts[layout].panels
    app.recalculate_layout(layout)
    wait()
    app.show("layout", layout)
    root.update()
    shot(root, "window-paired-layout" + suffix + ".png")
    app.show("graph", observed_index)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"paired-proportions.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension
    app.show("layout", layout)
    for extension, magic in (("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"paired-layout.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension

    # 11. CSV of every sheet; an infinite odds ratio is written as inf, an empty statistic stays empty.
    app.show("result", gains_index)
    for position, name in enumerate(("Paired counts", "Paired proportions")):
        app.result_tabs.select(position)
        target = out / f"paired-gains-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 2, name
        if name == "Paired proportions":
            assert exported.loc["Matched odds ratio", "Value"] in ("inf", "∞", "Infinity", float("inf")), exported
            assert pd.isna(exported.loc["Chi-square", "Value"]) or exported.loc["Chi-square", "Value"] == ""
    app.show("result", observed_index)
    app.result_tabs.select(2)
    target = out / "paired-pairs.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
    assert list(exported.columns) == ["Source row", "Before", "After", "Transition"] and len(exported) == 17, exported

    # 12. Save, reopen: canonical recipes, the same tables and the same bars, in both languages' worth of settings.
    def figure_state(run):
        if run.result.figure is None:
            return None
        axes = run.result.figure.axes[0]
        return axes.get_title(), [patch.get_height() for patch in axes.patches], [
            tick.get_text() for tick in axes.get_xticklabels()]

    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()},
                                        figure_state(run))
                for run in app.runs if run.method == PAIRED_PROPORTIONS and run.result is not None}
    assert len(expected) >= 8, sorted(expected)
    app.path = directory / "paired-proportions-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position, run in enumerate(app.runs):                       # each run recalculates when it is opened
        if run.method == PAIRED_PROPORTIONS:
            app.open_sheet(("graph" if run.options.get("Graph") else "result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs if run.method == PAIRED_PROPORTIONS}
    for key, (saved_options, tables, figure) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
        assert figure_state(reopened[key]) == figure, key
    key = next(k for k, v in expected.items() if v[0].get("Graph") and v[0]["Input format"] == "Observations")
    assert "#9b4174" in str(reopened[key].style)
    assert "Before" in reopened[key].options and "After negative counts" not in reopened[key].options
    reopened_index = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    app.show("graph", reopened_index)
    root.update()
    shot(root, "window-paired-reopened" + suffix + ".png")

    # 13. Use Result as Data keeps the source rows of Pairs.
    before_tables = set(app.tables)
    for position in (1, 2):
        app.show("result", reopened_index)
        app.result_tabs.select(position)
        app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 2, created
    assert any(list(f.columns) == ["Source row", "Before", "After", "Transition"] and len(f) == 17
               for f in created.values()), {k: list(v.columns) for k, v in created.items()}
    assert any(f.shape[0] >= 10 and "Value" in f.columns for f in created.values()), {
        k: (list(v.columns), len(v)) for k, v in created.items()}
    wait()
    assert app.pending is None and not errors, errors
