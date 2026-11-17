"""Desktop smoke check for the exact Mann–Whitney and Wilcoxon signed-rank tests.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=exact-rank-tests``) calls :func:`check_exact_rank_tests`
with a kit that carries app, root, directory, capture, pick_method, drive_dialog(action) and
wait_for_calculation. The two real dialogs are driven. Expected p values come from labelled enumeration
written here, independent of the counting code.
"""
from itertools import combinations, product
from tkinter import filedialog, messagebox
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import rank_exact
from .data import Dataset, save_project
from .rank_tests import (ALTERNATIVE, CONTINUITY, EXACT, MANN_WHITNEY, NORMAL, P_VALUE, WILCOXON,
                         ZERO_DIFFERENCES)

TITLE = "Rank data"
SCORE = [3., 5, 5, 8, 5, 9, 9, 12]
ARM = list("AABABBAB")
BEFORE = [10., 12, 9, 11, 13, 10, 14, 8]
AFTER = [10., 10, 10, 10, 10, 11, 9, 10]


def mann_expected(values, arms):
    """Return (less, greater, two-sided) p for the first arm seen, by listing every choice of positions."""
    values = np.asarray(values, dtype=float)
    first = np.asarray(arms) == arms[0]
    ranks = (2 * stats.rankdata(values)).astype(int)
    observed = ranks[first].sum()
    scores = [ranks[list(c)].sum() for c in combinations(range(len(values)), int(first.sum()))]
    low, high = (sum(s <= observed for s in scores) / len(scores), sum(s >= observed for s in scores) / len(scores))
    return low, high, min(1.0, 2 * min(low, high))


def wilcoxon_expected(first, second, pratt=False):
    """Return (less, greater, two-sided) p by listing every sign assignment of the nonzero differences."""
    difference = np.asarray(first, dtype=float) - np.asarray(second, dtype=float)
    ranks = (2 * stats.rankdata(np.abs(difference) if pratt else np.abs(difference[difference != 0]))).astype(int)
    keep = difference != 0
    used = ranks[keep] if pratt else ranks
    observed = used[difference[keep] > 0].sum()
    scores = [sum(r for r, plus in zip(used, signs) if plus) for signs in product((False, True), repeat=len(used))]
    low, high = (sum(s <= observed for s in scores) / len(scores), sum(s >= observed for s in scores) / len(scores))
    return low, high, min(1.0, 2 * min(low, high))


def check_exact_rank_tests(kit):
    app, directory, wait = kit.app, kit.directory, kit.wait_for_calculation
    path = directory / "exact-rank-tests.alab"
    data = pd.DataFrame({"Score": SCORE, "Arm": ARM, "Before": BEFORE, "After": AFTER})
    # Recipes saved before the P value option carry none of the new keys and keep the original sheets.
    save_project(path, {TITLE: Dataset(data, analyses=[
        (MANN_WHITNEY, {"Response": "Score", "Group": "Arm"}),
        (WILCOXON, {"First": "Before", "Second": "After"})])})
    app.import_file(path)
    for index in (0, 1):
        app.open_sheet(("result", index))
        wait()
    old_mann, old_wilcoxon = app.runs[0], app.runs[1]
    assert P_VALUE not in old_mann.options and P_VALUE not in old_wilcoxon.options
    assert list(old_mann.result.tables) == [MANN_WHITNEY] and list(old_wilcoxon.result.tables) == [WILCOXON]
    assert "p method" not in old_mann.result.tables[MANN_WHITNEY].index

    def rejected(dialog, field, text, shot=None):
        with patch.object(messagebox, "showerror") as report:
            assert dialog.validate() is False
        message = report.call_args.args[1]
        assert field in message and text in message, message
        assert dialog.winfo_exists()
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot:
            kit.capture(dialog, shot)

    def continuity_enabled(dialog):
        return "disabled" not in dialog.field_rows[CONTINUITY][1].state()

    # Mann–Whitney: defaults, an error on the Group field, the continuity switch, then Exact and Less.
    def mann_dialog(dialog):
        kit.pick_method(dialog, MANN_WHITNEY)
        controls = dialog.controls
        assert controls[P_VALUE][1].get() == "Automatic" and controls[ALTERNATIVE][1].get() == "Two-sided"
        assert controls[CONTINUITY][1].get() is True and continuity_enabled(dialog)
        assert ZERO_DIFFERENCES not in controls
        controls["Response"][1].set("Score")
        controls["Group"][1].set("Score")
        rejected(dialog, "Group", "Choose different columns", "window-rank-mann-error.png")
        controls["Group"][1].set("Arm")
        controls[P_VALUE][1].set(EXACT)
        dialog.update()
        assert not continuity_enabled(dialog)
        controls[P_VALUE][1].set(NORMAL)
        dialog.update()
        assert continuity_enabled(dialog)
        controls[P_VALUE][1].set(EXACT)
        controls[ALTERNATIVE][1].set("Less")
        dialog.fields.select(dialog.field_rows[P_VALUE][1].master)
        kit.capture(dialog, "window-rank-mann-options.png")

    app.show("data", TITLE)
    kit.drive_dialog(mann_dialog)
    app.choose_analysis()
    wait()
    mann = next(i for i, run in enumerate(app.runs) if run.method == MANN_WHITNEY and P_VALUE in run.options)
    table = app.runs[mann].result.tables[MANN_WHITNEY]["Value"]
    low, high, two = mann_expected(SCORE, ARM)
    assert table["p method"] == EXACT and abs(table["p"] - low) < 1e-12 and table["p method reason"] == ""
    assert table["U first"] + table["U second"] == 16 and table[ALTERNATIVE] == "Less"
    ranks = app.runs[mann].result.tables["Ranks"]
    # Source row is the worksheet index label of each complete row.
    assert ranks["Source row"].tolist() == list(range(8)) and ranks["Rank"].tolist()[1:4] == [3, 3, 5]
    app.show("result", mann)
    kit.capture(kit.root, "window-rank-mann-exact.png")
    app.result_tabs.select(1)
    kit.capture(kit.root, "window-rank-mann-ranks.png")

    # Wilcoxon: Pratt zeros with the exact p value, an error on the second column, and the Automatic fallback.
    def wilcoxon_dialog(dialog):
        kit.pick_method(dialog, WILCOXON)
        controls = dialog.controls
        assert controls[ZERO_DIFFERENCES][1].get() == "Discard" and controls[P_VALUE][1].get() == "Automatic"
        controls["First"][1].set("Before")
        controls["Second"][1].set("Before")
        rejected(dialog, "Second", "Choose different columns", "window-rank-wilcoxon-error.png")
        controls["Second"][1].set("After")
        controls[P_VALUE][1].set(EXACT)
        controls[ALTERNATIVE][1].set("Greater")
        controls[ZERO_DIFFERENCES][1].set("Pratt")
        dialog.fields.select(dialog.field_rows[P_VALUE][1].master)
        kit.capture(dialog, "window-rank-wilcoxon-options.png")

    app.show("data", TITLE)
    kit.drive_dialog(wilcoxon_dialog)
    app.choose_analysis()
    wait()
    wil = next(i for i, run in enumerate(app.runs) if run.method == WILCOXON and P_VALUE in run.options)
    table = app.runs[wil].result.tables[WILCOXON]["Value"]
    low, high, two = wilcoxon_expected(BEFORE, AFTER, pratt=True)
    assert table["p method"] == EXACT and abs(table["p"] - high) < 1e-12 and table[ZERO_DIFFERENCES] == "Pratt"
    assert (table["Zero pairs"], table["Effective N"], table["Complete pairs"]) == (1, 7, 8)
    pairs = app.runs[wil].result.tables["Ranks"]
    assert pairs["Included"].tolist() == [False] + [True] * 7 and pairs["Absolute rank"].iloc[0] == 1.0
    app.show("result", wil)
    kit.capture(kit.root, "window-rank-wilcoxon-exact.png")

    # The exact p value outside the work limit stays in the dialog on its field; Automatic falls back and says why.
    def over_limit(dialog):
        assert dialog.controls[P_VALUE][1].get() == EXACT
        rejected(dialog, P_VALUE, "limit", "window-rank-exact-error.png")
        dialog.controls[P_VALUE][1].set("Automatic")

    app.show("result", wil)
    wait()
    with patch.object(rank_exact, "MAX_STATES", 1):
        kit.drive_dialog(over_limit)
        app.edit_analysis()
        wait()
    table = app.runs[wil].result.tables[WILCOXON]["Value"]
    assert table["p method"] == NORMAL and "work limit" in table["p method reason"] and table[CONTINUITY] is True
    app.show("result", wil)
    kit.capture(kit.root, "window-rank-wilcoxon-fallback.png")

    # Editing a cell and excluding another recalculate both results.
    app.show("data", TITLE)
    app.edit_cell(2, 0, "6")                       # Score of the third row, a B observation
    wait()
    app.show("data", TITLE)
    app.current_grid.select((7, 2))                # Before of the last row
    app.toggle_exclusion()
    wait()
    scores = [3., 5, 6, 8, 5, 9, 9, 12]
    low, high, two = mann_expected(scores, ARM)
    table = app.runs[mann].result.tables[MANN_WHITNEY]["Value"]
    assert abs(table["p"] - low) < 1e-12 and table["p method"] == EXACT
    table = app.runs[wil].result.tables[WILCOXON]["Value"]
    assert table["Complete pairs"] == 7 and table["p method"] == EXACT, table
    ranks = app.runs[wil].result.tables["Ranks"]
    assert ranks["Source row"].tolist() == list(range(7))

    # CSV of the summary and of the ranks.
    app.show("result", mann)
    for sheet, columns in ((0, ["Value"]), (1, ["Source row", "Group", "Value", "Rank"])):
        app.result_tabs.select(sheet)
        target = directory / f"exact-rank-{sheet}.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        if sheet == 0:
            by_name = exported["Value"]
            assert by_name["p method"] == EXACT and by_name["First group"] == "A", by_name
        else:
            assert list(exported.columns) == columns and len(exported) == 8, list(exported.columns)

    # Save and reopen keep the recipes and the results.
    before = {index: app.runs[index].result.tables for index in (mann, wil)}
    options = {index: dict(app.runs[index].options) for index in (mann, wil)}
    assert app.save()
    app.import_file(path)
    for index in (mann, wil):
        app.open_sheet(("result", index))
        wait()
        assert app.runs[index].options == options[index]
        for name, frame in before[index].items():
            pd.testing.assert_frame_equal(app.runs[index].result.tables[name], frame)
    app.open_sheet(("result", 0))
    wait()
    assert P_VALUE not in app.runs[0].options and list(app.runs[0].result.tables) == [MANN_WHITNEY]

    # Italian: translated captions and choices on screen, canonical keys and values in the recipe.
    from . import i18n

    original_language = i18n.active_language()
    try:
        i18n.set_language("it")

        def italian(dialog):
            captions = {name: dialog.field_rows[name][0].cget("text")
                        for name in (P_VALUE, ALTERNATIVE, CONTINUITY, ZERO_DIFFERENCES)}
            assert captions == {P_VALUE: "Valore p", ALTERNATIVE: "Ipotesi alternativa",
                                CONTINUITY: "Correzione di continuità", ZERO_DIFFERENCES: "Differenze nulle"}, captions
            assert dialog.field_rows["First"][0].cget("text") == i18n.ui("First")
            p_field = dialog.field_rows[P_VALUE][1]
            assert dialog.controls[P_VALUE][1].get() == "Automatic" and p_field.get() == "Automatico"
            assert list(p_field.cget("values")) == ["Automatico", "Esatto condizionato", "Approssimazione normale"]
            assert list(dialog.field_rows[ALTERNATIVE][1].cget("values")) == ["Bilaterale", "Minore", "Maggiore"]
            assert list(dialog.field_rows[ZERO_DIFFERENCES][1].cget("values")) == ["Escludi", "Pratt"]
            p_field.set("Esatto condizionato")
            dialog.update()
            assert dialog.controls[P_VALUE][1].get() == EXACT and not continuity_enabled(dialog)
            with patch.object(rank_exact, "MAX_STATES", 1):
                rejected(dialog, P_VALUE, "limit", "window-rank-it-error.png")
            dialog.field_rows[ALTERNATIVE][1].set("Minore")
            dialog.field_rows[ZERO_DIFFERENCES][1].set("Escludi")
            assert dialog.controls[ALTERNATIVE][1].get() == "Less"
            assert dialog.controls[ZERO_DIFFERENCES][1].get() == "Discard"
            dialog.fields.select(dialog.field_rows[P_VALUE][1].master)
            kit.capture(dialog, "window-rank-it-options.png")

        app.show("result", wil)
        wait()
        kit.drive_dialog(italian)
        app.edit_analysis()
        wait()
        saved = app.runs[wil].options
        assert (saved[P_VALUE], saved[ALTERNATIVE], saved[ZERO_DIFFERENCES]) == (EXACT, "Less", "Discard"), saved
        low, _, _ = wilcoxon_expected(BEFORE[:7], AFTER[:7])
        assert abs(app.runs[wil].result.tables[WILCOXON]["Value"]["p"] - low) < 1e-12
        app.show("result", wil)
        kit.capture(kit.root, "window-rank-it-result.png")
        options = dict(saved)
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", wil))
        wait()
        assert app.runs[wil].options == options

        def italian_again(dialog):
            assert dialog.field_rows[P_VALUE][1].get() == "Esatto condizionato"
            assert dialog.field_rows[ALTERNATIVE][1].get() == "Minore"
            assert dialog.field_rows[ZERO_DIFFERENCES][1].get() == "Escludi"

        app.show("result", wil)
        kit.drive_dialog(italian_again)
        app.edit_analysis()
        wait()
        assert app.runs[wil].options == options
        i18n.set_language("en")

        def english(dialog):
            assert dialog.field_rows[P_VALUE][0].cget("text") == "P value"
            assert dialog.field_rows[P_VALUE][1].get() == EXACT
            assert dialog.field_rows[ALTERNATIVE][1].get() == "Less"
            assert dialog.field_rows[ZERO_DIFFERENCES][1].get() == "Discard"

        app.show("result", wil)
        kit.drive_dialog(english)
        app.edit_analysis()
        wait()
        assert app.runs[wil].options == options
    finally:
        i18n.set_language(original_language)

    # The ranks become a table to analyse further.
    app.open_sheet(("result", mann))
    wait()
    app.show("result", mann)
    app.result_tabs.select(1)
    app.use_result_as_data()
    used = app.selected[1]
    raw = app.tables[used].raw
    assert list(raw.columns) == ["Source row", "Group", "Value", "Rank"] and len(raw) == 8
    kit.capture(kit.root, "window-rank-ranks-as-data.png")
