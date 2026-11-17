"""Desktop smoke check for the ordinal trend after ordinary one-way ANOVA.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=anova-trend``) calls
:func:`check_anova_trend`. The result is a table: the product PDF export covers
graphs and layouts, so this check exports the trend sheet as CSV and records
the numbers there. It does not add a table-to-PDF feature.
"""
import json
import math
from unittest.mock import patch

import pandas as pd

from .data import Dataset, save_project
from .i18n import active_language, set_language
from .trend_anova import ORDER, TREND

TITLE = "balanced"
P_LINEAR = 2.7662610914284855e-05
PLANNED_EN = (
    "The linear and nonlinear tests are planned contrasts and are not adjusted for multiplicity. "
    "The slope is the change in the response for one group position, not for a dose written in the title."
)
BALANCED = """group,y
10,1
10,2
10,3
1,3
1,4
1,5
100,4
100,5
100,6
3,8
3,9
3,10
"""


def check_anova_trend(root, app, directory, kit):
    from tkinter import filedialog, messagebox

    capture, drive, pick = kit.capture, kit.drive_dialog, kit.pick_method
    wait = kit.wait_for_calculation
    previous_geometry = root.geometry()
    language = active_language()
    root.geometry("1024x768+0+0")
    try:
        _check(root, app, directory, capture, drive, pick, wait, messagebox, filedialog)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _notebook_page(dialog, widget):
    """Notebook tab that contains widget. One-way Options fields sit in a scrollable frame."""
    page = widget
    while page is not None and page.master is not dialog.fields:
        page = page.master
    return page


def _check(root, app, directory, capture, drive, pick, wait, messagebox, filedialog):
    source = directory / "balanced.csv"
    source.write_text(BALANCED, encoding="utf-8")
    app.import_file(source)
    data = app.tables[TITLE]
    # An all-numeric CSV column is stored as numbers. These titles are text.
    data.raw["group"] = data.raw["group"].astype("string")
    assert data.raw["group"].tolist() == ["10", "10", "10", "1", "1", "1", "100", "100", "100", "3", "3", "3"]
    assert not pd.api.types.is_numeric_dtype(data.raw["group"])
    trend_key = app.active_project
    set_language("it")

    def invalid(dialog, field, words):
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert all(word in message for word in words), message
        assert dialog.fields.select() == str(_notebook_page(dialog, dialog.field_rows[field][1])), field
        assert dialog.winfo_exists()
        dialog.result = None
        dialog.ok = dialog.cancel

    def show_options(dialog):
        dialog.fields.select(_notebook_page(dialog, dialog.field_rows[TREND][0]))
        dialog.update_idletasks()

    def configure_off(dialog):
        pick(dialog, "One-way ANOVA")
        dialog.controls["Response"][1].set("y")
        dialog.controls["Group"][1].set("group")
        dialog.controls["Method"][1].set("Ordinary")
        dialog.controls["Post-hoc"][1].set("Tukey")
        dialog.update_idletasks()
        assert dialog.controls[TREND][1].get() is False
        assert not dialog.field_rows[ORDER][1].grid_info()
        assert dialog.field_rows[TREND][0].cget("text") == "Trend lineare"
        assert dialog.field_rows[ORDER][0].cget("text") == "Ordine dei gruppi del trend"
        show_options(dialog)
        assert dialog.winfo_reqwidth() <= 1024, dialog.winfo_reqwidth()
        assert dialog.winfo_reqheight() <= 768, dialog.winfo_reqheight()
        capture(dialog, "01-default-it.png")

    drive(configure_off)
    app.choose_analysis()
    wait()
    # The full smoke already has other runs. This check follows the one it just added.
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.title == TITLE
    assert run.options["Method"] == "Ordinary" and run.options["Post-hoc"] == "Tukey"
    assert run.options[TREND] is False and ORDER not in run.options
    assert "Linear trend" not in run.result.tables
    legacy_names = list(run.result.tables)

    def enable(dialog):
        widget = dialog.controls[ORDER][1]
        dialog.controls[TREND][1].set(True)
        dialog.update_idletasks()
        assert dialog.field_rows[ORDER][1].grid_info()
        assert [item["value"] for item in widget.values()] == ["10", "1", "100", "3"]
        assert [item["kind"] for item in widget.values()] == ["text"] * 4
        shown = list(widget.listbox.get(0, "end"))
        assert shown == ["1   10", "2   1", "3   100", "4   3"], shown
        assert "posizioni" in widget.note.cget("text")
        show_options(dialog)
        assert widget.listbox.winfo_ismapped()
        capture(dialog, "02-order-it.png")

    app.show("result", index)
    drive(enable)
    app.edit_analysis()
    wait()
    run = app.runs[index]
    metrics = _metrics(run)
    assert metrics["Slope"] == 2.2
    assert metrics["R² effect"] != metrics["R² alerting"]
    assert math.isclose(metrics["p linear"], P_LINEAR, rel_tol=1e-9, abs_tol=0)
    assert "pianificati" in metrics["Note"]
    assert "ordinal" in metrics["Convention"]
    assert list(run.result.tables)[:len(legacy_names)] == legacy_names
    assert run.result.tables["Trend group means"]["Group value"].tolist() == ["10", "1", "100", "3"]
    _show_trend(app, index)
    capture(root, "03-results-it.png")
    original_p = metrics["p linear"]

    def reverse(dialog):
        widget = dialog.controls[ORDER][1]
        count = len(widget.items)
        for steps in range(count - 1, 0, -1):
            widget.listbox.selection_clear(0, "end")
            widget.listbox.selection_set(count - 1)
            for _ in range(steps):
                widget.move(-1)
        assert [item["value"] for item in widget.values()] == ["3", "100", "1", "10"]

    app.show("result", index)
    drive(reverse)
    app.edit_analysis()
    wait()
    flipped = _metrics(app.runs[index])
    assert flipped["Slope"] == -2.2
    assert math.isclose(flipped["p linear"], original_p, rel_tol=0, abs_tol=0)
    assert math.isclose(flipped["R² effect"], metrics["R² effect"], rel_tol=0, abs_tol=0)
    assert app.runs[index].result.tables["Trend group means"]["Group value"].tolist() == ["3", "100", "1", "10"]
    _show_trend(app, index)
    capture(root, "04-reversed.png")

    def welch(dialog):
        dialog.controls["Post-hoc"][1].set("None")
        dialog.controls["Method"][1].set("Welch")
        dialog.update_idletasks()
        invalid(dialog, TREND, ("Linear trend", "ordinaria"))
        show_options(dialog)
        capture(dialog, "05-welch-error.png")

    app.show("result", index)
    drive(welch)
    app.edit_analysis()
    wait()
    kept = app.runs[index]
    assert kept.options["Method"] == "Ordinary" and kept.options[TREND] is True
    assert _metrics(kept)["Slope"] == -2.2
    assert len(app.runs) == index + 1

    rows = [index for index, value in enumerate(app.tables[TITLE].raw["group"].tolist()) if value == "3"]
    assert rows == [9, 10, 11]
    app.show("data", TITLE)
    for row in rows:
        app.current_grid.select((row, 1))
        app.toggle_exclusion()
        wait()

    def excluded(dialog):
        widget = dialog.controls[ORDER][1]
        assert any(item["value"] == "3" for item in widget.values())
        assert any("3" in line and "rimosso" in line for line in widget.listbox.get(0, "end"))
        invalid(dialog, ORDER, ("Trend group order", "3"))
        show_options(dialog)
        capture(dialog, "06-exclusion-error.png")

    app.show("result", index)
    wait()
    drive(excluded)
    app.edit_analysis()
    assert app.runs[index].options[ORDER][0]["value"] == "3"
    for _ in range(len(rows)):
        app.apply_worksheet_history()
        wait()
    assert not app.tables[TITLE].excluded
    app.show("result", index)
    wait()
    assert _metrics(app.runs[index])["Slope"] == -2.2

    _typed_levels(app, directory, drive, pick, capture, trend_key)
    assert app.switch_project(trend_key)
    assert _metrics(app.runs[index])["Slope"] == -2.2

    project = directory / "anova-trend.alab"
    app.path = project
    assert app.save()
    saved = json.loads(project.read_text(encoding="utf-8"))
    recipe = next(options for table in saved["tables"] if table["title"] == TITLE
                  for _method, options in table["analyses"])
    assert recipe["Linear trend"] is True
    assert recipe["Trend group order"][0] == {"kind": "text", "value": "3"}
    assert "analysis.trend" not in project.read_text(encoding="utf-8")
    assert "Trend lineare" not in project.read_text(encoding="utf-8")
    app.import_file(project)
    index = next(i for i, run in enumerate(app.runs) if run.title == TITLE and run.options.get(TREND) is True)
    app.open_sheet(("result", index))
    wait()
    reopened = app.runs[index]
    assert reopened.options[TREND] is True
    assert [item["value"] for item in reopened.options[ORDER]] == ["3", "100", "1", "10"]
    assert _metrics(reopened)["Slope"] == -2.2
    _show_trend(app, index)
    capture(root, "08-reopened.png")

    legacy = directory / "v061-anova.alab"
    frame = pd.read_csv(source, dtype={"group": "string", "y": "float64"})
    save_project(legacy, {TITLE: Dataset(frame, analyses=[(
        "One-way ANOVA", {"Response": "y", "Group": "group", "Method": "Ordinary", "Post-hoc": "Tukey"})])})
    legacy_key = app.add_project()
    assert legacy_key is not None
    app.import_file(legacy)
    app.open_sheet(("result", 0))
    wait()
    old = app.runs[0]
    assert "Linear trend" not in old.options and "Trend group order" not in old.options
    assert "Linear trend" not in old.result.tables
    assert "ANOVA" in old.result.tables
    assert app.switch_project(trend_key)
    app.remove_project_tab(legacy_key)

    def english(dialog):
        assert dialog.field_rows[TREND][0].cget("text") == "Linear trend"
        assert dialog.field_rows[ORDER][0].cget("text") == "Trend group order"
        assert [item["value"] for item in dialog.controls[ORDER][1].values()] == ["3", "100", "1", "10"]
        show_options(dialog)

    set_language("en")
    app.show("result", index)
    drive(english)
    app.edit_analysis()
    wait()
    english_metrics = _metrics(app.runs[index])
    assert english_metrics["Note"] == PLANNED_EN
    assert english_metrics["Slope"] == -2.2
    assert "analysis.trend" not in english_metrics["Note"]
    _show_trend(app, index)
    grid = app.result_tabs.nametowidget(app.result_tabs.select())
    grid.tree.see(grid.tree.get_children()[-1])
    capture(root, "09-results-en.png")
    csv_path = directory / "linear-trend.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    note = exported.loc[exported["Metric"] == "Note", "Value"].iloc[0]
    slope = float(exported.loc[exported["Metric"] == "Slope", "Value"].iloc[0])
    assert note == PLANNED_EN
    assert slope == -2.2
    assert "…" not in note and len(note) == len(PLANNED_EN)


def _typed_levels(app, directory, drive, pick, capture, trend_key):
    seed = directory / "typed-seed.alab"
    save_project(seed, {"typed": Dataset(pd.DataFrame({
        "group": [1, 1, 1, 1, 2, 2], "y": [1.0, 2.0, 8.0, 9.0, 4.0, 5.0]}))})
    typed_key = app.add_project()
    assert typed_key is not None
    app.import_file(seed)
    # save_project keeps one kind per column, so the mixed identities are built in memory.
    app.tables["typed"].raw = pd.DataFrame({
        "group": pd.Series([1, 1, "1", "1", 2, 2], dtype=object),
        "y": [1.0, 2.0, 8.0, 9.0, 4.0, 5.0],
    })

    def show(dialog):
        pick(dialog, "One-way ANOVA")
        dialog.controls["Response"][1].set("y")
        dialog.controls["Group"][1].set("group")
        dialog.controls[TREND][1].set(True)
        dialog.update_idletasks()
        widget = dialog.controls[ORDER][1]
        assert [(item["kind"], item["value"]) for item in widget.values()] == [
            ("number", 1), ("text", "1"), ("number", 2)]
        captions = list(widget.listbox.get(0, "end"))
        assert any("1 [numero]" in line for line in captions), captions
        assert any("1 [testo]" in line for line in captions), captions
        dialog.fields.select(_notebook_page(dialog, dialog.field_rows[ORDER][0]))
        dialog.update_idletasks()
        capture(dialog, "07-typed-levels.png")
        dialog.result = None
        dialog.ok = dialog.cancel

    drive(show)
    app.choose_analysis()
    assert app.switch_project(trend_key)
    app.remove_project_tab(typed_key)


def _metrics(run):
    return run.result.tables["Linear trend"]["Value"].to_dict()


def _show_trend(app, index):
    app.show("result", index)
    tabs = app.result_tabs
    selected = next(tab for tab in tabs.tabs() if tabs.tab(tab, "text") == "Linear trend")
    tabs.select(selected)
    tabs.update_idletasks()
