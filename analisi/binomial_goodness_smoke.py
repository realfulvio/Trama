"""Desktop smoke for the exact binomial test in Compare observed distribution with expected.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=binomial-goodness``) calls :func:`check_binomial_goodness`.
The real window is used and Analyze is driven through the dialog; widgets are driven and events are generated,
which is not a native pointer session. The main flow runs in the language of the preferences and one dialog in the
other language follows. Recipe values stay canonical English whichever language is shown.
"""
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from unittest.mock import patch
import json
import time

import numpy as np
import pandas as pd

from .exact_binomial import EXACT, PEARSON
from .field_error import FieldError
from .i18n import active_language, set_language, tr, ui
from .parts_of_whole import GOODNESS_OF_FIT, TEST_METHOD
from .workbench import analyse

TITLE = "Counts"
LEVEL = "Confidence level (%)"
EXPECTED_VALUES = json.loads(
    (Path(__file__).resolve().parents[1] / "tests" / "data" / "exact_binomial" / "expected.json").read_text(encoding="utf-8"))
LEGACY = {"Observed counts": "Count", "Row titles": "Row title", "Expected distribution": "Weights in a column",
          "Expected values": "Weight", "Estimated parameters": 0}
WORDS = {"en": {"two": "exactly two observed categories", "level": "strictly between 0 and 100",
                "reset": "set back to 0", "label": "Test method", "choice": "Exact binomial"},
         "it": {"two": "esattamente due categorie osservate", "level": "strettamente compreso tra 0 e 100",
                "reset": "riportati a 0", "label": "Metodo del test", "choice": "Binomiale esatto"}}


def _frame():
    """Synthetic worksheet: two observed rows around a skipped one, plus a three-row column."""
    return pd.DataFrame({"Row title": ["Signal $", "Skip", "Other"], "Count": [7, None, 93],
                         "Weight": [2, None, 8], "Expected": [20, None, 80], "Three": [7, 5, 93]})


def _shown(widget):
    """Gridded: a field that the dialog hid with grid_remove has no geometry manager."""
    return widget.winfo_manager() != ""


def check_binomial_goodness(root, app, directory, kit):
    directory = Path(directory)
    previous_language = active_language()
    start = previous_language if previous_language in ("en", "it") else "en"
    set_language(start)
    other = "it" if start == "en" else "en"

    def find(parent=None):
        parent = root if parent is None else parent
        for child in parent.winfo_children():
            if isinstance(child, kit.AnalysisDialog):
                return child
            found = find(child)
            if found is not None:
                return found
        return None

    def drive(action, *, accept=True):
        holder = {}
        deadline = time.monotonic() + 30

        def enter():
            dialog = find()
            if dialog is None or not dialog.winfo_viewable():
                if time.monotonic() < deadline:
                    root.after(40, enter)
                    return
                holder["error"] = TimeoutError("The analysis dialog did not open.")
                return

            def unexpected(_title, message, **_kwargs):
                raise AssertionError(message)

            try:
                dialog.update_idletasks()
                with patch.object(messagebox, "showerror", side_effect=unexpected):
                    action(dialog)
                    if accept:
                        dialog.ok()
                    else:
                        dialog.result = None
                        dialog.cancel()
            except Exception as error:
                holder["error"] = error
                try:
                    dialog.result = None
                    dialog.cancel()
                except Exception:
                    pass

        root.after(200, enter)
        return holder

    def finish(holder):
        if "error" in holder:
            raise holder["error"]

    def buttons(dialog):
        """Run Analysis and Cancel stay fully visible inside the screen."""
        dialog.update_idletasks()
        found = {}
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found[widget.cget("text")] = widget
        height, width = root.winfo_screenheight(), root.winfo_screenwidth()
        for name in ("Run Analysis", "Cancel"):
            widget = found[ui(name)]
            assert widget.winfo_ismapped() and widget.winfo_viewable(), name
            assert 0 <= widget.winfo_rootx() and widget.winfo_rootx() + widget.winfo_width() <= width, name
            assert 0 <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= height, name

    def open_page(dialog, field):
        """Bring the notebook page that holds ``field`` to the front, so screenshots show it."""
        page = dialog.field_rows[field][0].master
        while page is not None and page.master is not dialog.fields:
            page = page.master
        dialog.fields.select(page)
        dialog.update()

    def reject(dialog, field, snippet):
        """The dialog refuses the recipe, stays open, shows the page of the field and parks the focus on it."""
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert snippet in message, message
        assert ui(field).casefold() in message.casefold() or field in message, message
        assert dialog.winfo_exists()
        _, widget = dialog.field_rows[field]
        target = widget.focus_target() if hasattr(widget, "focus_target") else (
            widget.winfo_children()[0] if isinstance(widget, ttk.Frame) and widget.winfo_children() else widget)
        page = widget.master
        while page is not None and page.master is not dialog.fields:
            page = page.master
        assert dialog.fields.select() == str(page), (field, dialog.fields.select())
        assert dialog.initial_focus is target, field
        held = dialog.focus_get()
        assert held is None or held is target, (field, held)
        dialog.result = None
        return message

    def expected_report(options, frame=None):
        return analyse(GOODNESS_OF_FIT, app.tables[TITLE].frame(mask_excluded=True) if frame is None else frame,
                       options).tables

    def sections(name):
        return next(items for title, items, *_rest in app.sheet_sections() if title == name)

    try:
        words = WORDS[start]
        before = directory / "binomial-goodness-before.alab"
        kit.save_project(before, {TITLE: kit.Dataset(_frame(), analyses=[(GOODNESS_OF_FIT, dict(LEGACY))])})
        app.import_file(before)
        root.update()
        app.open_sheet(("result", 0))
        kit.wait_for_calculation()
        legacy = app.runs[0]
        assert TEST_METHOD not in legacy.options
        pearson = legacy.result.tables
        assert list(pearson) == ["Test", "Categories"] and legacy.result.figure is None
        assert list(pearson["Test"].index) == ["Pearson χ²", "df", "p", "Total count", "Minimum expected count"]
        assert list(pearson["Categories"].columns) == ["Category", "Observed", "Expected", "Pearson residual",
                                                       "Contribution"]
        assert abs(pearson["Test"].loc["Pearson χ²", "Value"] - 10.5625) < 1e-12
        legacy_tables = {name: table.copy() for name, table in pearson.items()}
        order_before = [name for name, _ref in sections("Results")]

        # Cancel leaves the saved Pearson run exactly as it was.
        dirty = app.dirty
        cancelled = drive(lambda dialog: kit.pick_method(dialog, GOODNESS_OF_FIT), accept=False)
        app.choose_analysis()
        finish(cancelled)
        assert len(app.runs) == 1 and app.dirty is dirty

        def configure(dialog):
            kit.pick_method(dialog, GOODNESS_OF_FIT)
            dialog.update()
            fields = dialog.field_rows
            # Pearson is the default and keeps its own fields.
            assert dialog.controls[TEST_METHOD][1].get() == PEARSON
            assert _shown(fields["Estimated parameters"][0]) and not _shown(fields[LEVEL][0])
            assert fields[TEST_METHOD][0].cget("text") == words["label"]
            assert dialog.goodness_note.cget("text") == ""
            open_page(dialog, TEST_METHOD)
            buttons(dialog)
            kit.capture(dialog, f"window-binomial-pearson-{start}.png")
            # Switching to Exact with a parameter count in plain view resets it explicitly.
            dialog.controls["Estimated parameters"][1].set("1")
            dialog.controls[TEST_METHOD][1].set(EXACT)
            dialog.update()
            assert dialog.choice_bindings[TEST_METHOD].display.get() == words["choice"]
            assert not _shown(fields["Estimated parameters"][0]) and _shown(fields[LEVEL][0])
            assert dialog.controls["Estimated parameters"][1].get() == "0"
            assert words["reset"] in dialog.goodness_note.cget("text"), dialog.goodness_note.cget("text")
            assert dialog.controls[LEVEL][1].get() == "95.0"
            assert fields[LEVEL][0].winfo_ismapped() and dialog.goodness_note.winfo_ismapped()
            kit.capture(dialog, f"window-binomial-reset-{start}.png")
            # Back to Pearson restores its fields, then to Exact shows the plain description.
            dialog.controls[TEST_METHOD][1].set(PEARSON)
            dialog.update()
            assert _shown(fields["Estimated parameters"][0]), ("estimated", dialog.controls[TEST_METHOD][1].get(),
                                                                fields["Estimated parameters"][0].winfo_manager())
            assert not _shown(fields[LEVEL][0]), "level"
            dialog.controls[TEST_METHOD][1].set(EXACT)
            dialog.update()
            assert dialog.goodness_note.cget("text") == tr("goodness.note.exact")
            # Three filled rows keep the dialog open and name Observed counts.
            dialog.controls["Observed counts"][1].set("Three")
            reject(dialog, "Observed counts", words["two"])
            kit.capture(dialog, f"window-binomial-three-{start}.png")
            dialog.controls["Observed counts"][1].set("Count")
            dialog.controls["Row titles"][1].set("Row title")
            dialog.controls["Expected distribution"][1].set("Weights in a column")
            dialog.controls["Expected values"][1].set("Weight")
            # The level is checked on its own field and keeps the dialog open.
            dialog.controls[LEVEL][1].set("100")
            reject(dialog, LEVEL, words["level"])
            dialog.controls[LEVEL][1].set("abc")
            reject(dialog, LEVEL, "")
            dialog.controls[LEVEL][1].set("99,9")
            open_page(dialog, TEST_METHOD)
            buttons(dialog)
            kit.capture(dialog, f"window-binomial-ready-{start}.png")
            assert dialog.validate() is True
            assert dialog.processing_result is not None
            assert "Estimated parameters" not in dialog.result[1]
            dialog.result = None

        holder = drive(configure)
        app.choose_analysis()
        finish(holder)
        kit.wait_for_calculation()
        assert not kit.errors, kit.errors

        run = next(item for item in app.runs if item.options.get(TEST_METHOD) == EXACT)
        index = app.runs.index(run)
        assert run.method == GOODNESS_OF_FIT
        assert list(run.options) == ["Observed counts", "Row titles", TEST_METHOD, "Expected distribution",
                                     "Expected values", LEVEL]
        assert run.options[LEVEL] == 99.9 and "Estimated parameters" not in run.options
        assert all(isinstance(key, str) and key.isascii() for key in run.options)
        assert run.result.figure is None and list(run.result.tables) == ["Test", "Categories"]
        report = run.result.tables["Test"]["Value"]
        for key, value in EXPECTED_VALUES.items():
            if key.startswith("CI"):
                continue
            assert abs(report[key] / value - 1) < 1e-11, key
        assert report["Method"] == EXACT and report[LEVEL] == 99.9 and report["Total count"] == 100
        assert report["CI lower"] < EXPECTED_VALUES["CI lower"] < EXPECTED_VALUES["CI upper"] < report["CI upper"]
        assert run.result.tables["Categories"]["Category"].tolist() == ["Signal $", "Other"]
        assert (run.name, ("graph", index)) not in sections("Graphs")
        assert (run.name, ("result", index)) in sections("Results")
        # The Pearson run is untouched and keeps its place and tables.
        assert app.runs[0] is legacy
        for name, table in legacy_tables.items():
            pd.testing.assert_frame_equal(legacy.result.tables[name], table)
        assert [name for name, _ref in sections("Results")][:len(order_before)] == order_before

        app.show("result", index)
        app.result_tabs.select(0)
        kit.capture(root, f"window-binomial-results-{start}.png")
        csv_path = directory / "binomial-test.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        text = csv_path.read_text(encoding="utf-8")
        exported = pd.read_csv(csv_path, index_col=0)
        for key in ("p lower", "p upper", "p", "CI lower", "CI upper"):
            assert repr(float(report[key])) in text, key
            assert float(exported.loc[key, "Value"]) == float(report[key]), key
        assert exported.loc["Method", "Value"] == EXACT
        # The categories table feeds a new data sheet and the Pearson statistic can be built from it.
        app.result_tabs.select(1)
        before_tables = set(app.tables)
        app.use_result_as_data()
        derived = next(name for name in app.tables if name not in before_tables)
        raw = app.tables[derived].raw
        assert list(raw.columns) == ["Category", "Observed", "Expected"]
        assert raw["Observed"].tolist() == [7, 93]
        chained = expected_report({"Observed counts": "Observed", "Row titles": "Category",
                                   "Expected distribution": "Expected counts in a column",
                                   "Expected values": "Expected"}, app.tables[derived].frame(mask_excluded=True))
        assert abs(chained["Test"].loc["Pearson χ²", "Value"] - 10.5625) < 1e-9
        app.show("result", index)

        # Save, reopen and recalculate from the stored recipe.
        after = directory / "binomial-goodness-after.alab"
        app.path = after
        assert app.save()
        app.import_file(after)
        root.update()
        exact_index = next(i for i, item in enumerate(app.runs) if item.options.get(TEST_METHOD) == EXACT)
        assert app.runs[exact_index].result is None
        app.open_sheet(("result", exact_index))
        kit.wait_for_calculation()
        reopened = app.runs[exact_index]
        assert reopened.options == run.options and list(reopened.options) == list(run.options)
        for name in ("Test", "Categories"):
            pd.testing.assert_frame_equal(reopened.result.tables[name], run.result.tables[name])
        # The run object keeps its identity and takes each new result: keep a copy of the calculated tables.
        saved_test = reopened.result.tables["Test"].copy()
        legacy_index = next(i for i, item in enumerate(app.runs) if TEST_METHOD not in item.options)
        app.open_sheet(("result", legacy_index))
        kit.wait_for_calculation()
        for name, table in legacy_tables.items():
            pd.testing.assert_frame_equal(app.runs[legacy_index].result.tables[name], table)
        assert [name for name, _ref in sections("Results")][:len(order_before)] == order_before
        app.show("result", exact_index)

        # Edit a count: the result follows. Exclude the title: the label falls back to the row number.
        app.show("data", TITLE)
        app.edit_cell(0, 1, "9")
        kit.wait_for_calculation()
        edited = app.runs[exact_index]
        again = expected_report(edited.options)
        assert edited.result.tables["Test"]["Value"]["Total count"] == 102
        assert edited.result.tables["Test"]["Value"]["Observed proportion"] == 9 / 102
        pd.testing.assert_frame_equal(edited.result.tables["Test"], again["Test"])
        assert edited.result.tables["Test"]["Value"]["p"] != saved_test["Value"]["p"]
        app.show("data", TITLE)
        app.current_grid.select((0, 0))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        titled = app.runs[exact_index]
        assert titled.result.tables["Categories"]["Category"].tolist() == ["Row 1", "Other"]
        app.show("data", TITLE)
        app.current_grid.select((0, 0))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        # Excluding a count leaves one observed row: the recalculation fails with a message and nothing is stale.
        app.show("data", TITLE)
        app.current_grid.select((2, 1))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        broken = app.runs[exact_index]
        assert broken.result is None and app.runs[legacy_index].result is None
        assert "need attention" in app.status.get(), app.status.get()
        try:
            expected_report(broken.options)
        except FieldError as error:
            assert error.field == "Observed counts" and "exactly two" in str(error), error
        else:
            raise AssertionError("One observed row was accepted")
        app.show("data", TITLE)
        app.current_grid.select((2, 1))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        assert app.runs[exact_index].result is not None and app.runs[legacy_index].result is not None
        assert app.runs[exact_index].result.tables["Test"]["Value"]["Total count"] == 102
        app.edit_cell(0, 1, "7")
        kit.wait_for_calculation()
        pd.testing.assert_frame_equal(app.runs[exact_index].result.tables["Test"], saved_test)

        # The same dialog in the other language, started from the saved Exact recipe.
        set_language(other)
        words = WORDS[other]
        app.show("result", exact_index)

        def second_language(dialog):
            dialog.update()
            fields = dialog.field_rows
            assert dialog.controls[TEST_METHOD][1].get() == EXACT
            assert fields[TEST_METHOD][0].cget("text") == words["label"]
            assert dialog.choice_bindings[TEST_METHOD].display.get() == words["choice"]
            assert dialog.goodness_note.cget("text") == tr("goodness.note.exact")
            assert not _shown(fields["Estimated parameters"][0]) and _shown(fields[LEVEL][0])
            open_page(dialog, TEST_METHOD)
            buttons(dialog)
            kit.capture(dialog, f"window-binomial-fields-{other}.png")
            dialog.controls["Observed counts"][1].set("Three")
            reject(dialog, "Observed counts", words["two"])
            kit.capture(dialog, f"window-binomial-three-{other}.png")
            dialog.controls["Observed counts"][1].set("Count")
            dialog.controls[LEVEL][1].set("0")
            reject(dialog, LEVEL, words["level"])
            kit.capture(dialog, f"window-binomial-level-{other}.png")
            dialog.controls[LEVEL][1].set("90")
            dialog.controls["Estimated parameters"][1].set("2")
            dialog.controls[TEST_METHOD][1].set(PEARSON)
            dialog.update()
            assert _shown(fields["Estimated parameters"][0]) and not _shown(fields[LEVEL][0])
            dialog.controls[TEST_METHOD][1].set(EXACT)
            dialog.update()
            assert words["reset"] in dialog.goodness_note.cget("text")
            assert dialog.validate() is True
            assert "Estimated parameters" not in dialog.result[1] and dialog.result[1][LEVEL] == 90.0
            dialog.result = None

        holder = drive(second_language)
        app.edit_analysis()
        finish(holder)
        kit.wait_for_calculation()
        narrowed = app.runs[exact_index]
        assert narrowed.options[LEVEL] == 90.0 and narrowed.options[TEST_METHOD] == EXACT
        narrow, wide = narrowed.result.tables["Test"]["Value"], saved_test["Value"]
        for key in ("p lower", "p upper", "p", "Observed proportion", "Null proportion"):
            assert narrow[key] == wide[key], key
        assert narrow["CI upper"] - narrow["CI lower"] < wide["CI upper"] - wide["CI lower"]
        app.show("result", exact_index)
        kit.capture(root, f"window-binomial-results-{other}.png")

        # A recipe that asks for parameter estimation with the exact test is refused by name.
        try:
            analyse(GOODNESS_OF_FIT, app.tables[TITLE].frame(), {**narrowed.options, "Estimated parameters": 1})
        except FieldError as error:
            assert error.field == "Estimated parameters"
        else:
            raise AssertionError("Estimated parameters with Exact was accepted")
        assert np.isfinite(float(narrow["CI lower"]))
    finally:
        set_language(previous_language)
