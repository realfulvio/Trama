"""Desktop smoke check for optional nonlinear fit diagnostics.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=fit-quality``) calls
:func:`check_fit_quality`. Fixture numbers are written here; the check does not
read the assignment package. The integrated check also exercises a confidence
band and the raw residual panel on the same fitted curve.
"""
import json
import math
from unittest.mock import patch

import pandas as pd

from .data import Dataset, save_project
from .fit_quality import REPLICATES, RESIDUAL_VIEW, RUNS
from .i18n import active_language, set_language, tr

METHOD = "Nonlinear regression"
P_FEW = 12 / 924
P_MANY = 68 / 70
P_LOF = 0.0006523706476901394
RUNS_REASON_IT = (
    "Coda inferiore esatta condizionata ai conteggi dei segni. "
    "Questo non dimostra che gli errori siano indipendenti."
)
RUNS_REASON_EN = (
    "Exact lower tail conditional on the sign counts. "
    "This does not prove that the errors are independent."
)
CURVED = """X,Y
0,15
1,15
2,15
3,13
4,15
5,17
6,19
7,21
8,23
9,29
10,33
11,37
"""
ALTERNATING = """X,Y
0,11
1,11
2,15
3,15
4,17
5,21
6,21
7,25
"""
REPLICATE_CURVED = """X,Y
0,1
0,2
0,3
1,2
1,3
1,4
2,5
2,6
2,7
3,10
3,11
3,12
4,17
4,18
4,19
"""
UNSORTED = """X,Y
1,15
0,15
2,15
3,13
4,15
5,17
6,19
7,21
8,23
9,29
10,33
11,37
"""
LEGACY = """X,Y
0,1.2
1,2.1
2,2.9
3,5.1
4,5.9
5,9.4
6,10.1
7,12.7
8,16.0
9,17.4
"""
CURVED_PAIRS = (
    (0, 15), (1, 15), (2, 15), (3, 13), (4, 15), (5, 17),
    (6, 19), (7, 21), (8, 23), (9, 29), (10, 33), (11, 37),
)


def check_fit_quality(root, app, directory, kit):
    from tkinter import filedialog, messagebox

    capture, drive, pick = kit.capture, kit.drive_dialog, kit.pick_method
    select, wait = kit.select_columns, kit.wait_for_calculation
    previous_geometry = root.geometry()
    language = active_language()
    root.geometry("1024x768+0+0")
    try:
        _check(root, app, directory, capture, drive, pick, select, wait, messagebox, filedialog)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _check(root, app, directory, capture, drive, pick, select, wait, messagebox, filedialog):
    project = app.active_project
    set_language("it")

    def invalid(dialog, field, words):
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert all(word in message for word in words), message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        assert dialog.winfo_exists()
        dialog.result = None
        dialog.ok = dialog.cancel

    def show_options(dialog):
        dialog.fields.select(dialog.field_rows[RUNS][0].master)
        dialog.update_idletasks()

    def note(dialog):
        parent = dialog.field_rows[RUNS][0].master
        return next(child.cget("text") for child in parent.winfo_children()
                    if child.winfo_class() == "TLabel"
                    and child.cget("text") == tr("analysis.fit.note.diagnostics"))

    def prepare(dialog, responses, groups=(), *, runs=False, replicates=False, residuals=False,
                weighting="Unweighted"):
        pick(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        select(dialog, "Y columns", set(responses))
        if groups:
            select(dialog, "Grouping variables", set(groups))
        dialog.controls["Model"][1].set("Straight line")
        dialog.controls["Weighting"][1].set(weighting)
        dialog.controls[RUNS][1].set(runs)
        dialog.controls[REPLICATES][1].set(replicates)
        dialog.controls[RESIDUAL_VIEW][1].set(residuals)
        dialog.update_idletasks()

    def load(name, text):
        source = directory / f"{name}.csv"
        source.write_text(text, encoding="utf-8")
        app.import_file(source)
        app.show("data", name)
        return name

    def run_dialog(action):
        drive(action)
        app.choose_analysis()
        wait()
        return app.runs[-1]

    def show_sheet(index, title):
        app.show("result", index)
        tabs = app.result_tabs
        selected = next(tab for tab in tabs.tabs() if tabs.tab(tab, "text") == title)
        tabs.select(selected)
        tabs.update_idletasks()
        grid = tabs.nametowidget(selected)
        children = grid.tree.get_children()
        if children:
            grid.tree.see(children[-1])

    # 1. Defaults stay off and add no diagnostic sheet or residual panel.
    load("legacy", LEGACY)

    def defaults(dialog):
        prepare(dialog, ["Y"])
        assert dialog.controls[RUNS][1].get() is False
        assert dialog.controls[REPLICATES][1].get() is False
        assert dialog.controls[RESIDUAL_VIEW][1].get() is False
        assert dialog.field_rows[RUNS][0].cget("text") == "Test delle sequenze"
        assert dialog.field_rows[REPLICATES][0].cget("text") == "Mancato adattamento tra repliche"
        assert dialog.field_rows[RESIDUAL_VIEW][0].cget("text") == "Residui rispetto a X"
        show_options(dialog)
        shown = note(dialog)
        assert "senza pesi" in shown and "residui grezzi" in shown, shown
        note_widget = next(child for child in dialog.field_rows[RUNS][0].master.winfo_children()
                           if child.winfo_class() == "TLabel" and child.cget("text") == shown)
        assert note_widget.winfo_ismapped() and note_widget.winfo_viewable()
        assert dialog.winfo_reqwidth() <= 1024, dialog.winfo_reqwidth()
        assert dialog.winfo_reqheight() <= 768, dialog.winfo_reqheight()
        capture(dialog, "01-default-it.png")

    legacy_run = run_dialog(defaults)
    assert legacy_run.options["Model"] == "Straight line"
    assert legacy_run.options[RUNS] is False
    assert legacy_run.options[REPLICATES] is False
    assert legacy_run.options[RESIDUAL_VIEW] is False
    assert list(legacy_run.result.tables) == ["Parameters: All", "Fit: All", "Residuals: All"]
    assert len(legacy_run.result.figure.axes) == 1
    assert not any("resid" in ax.get_ylabel().lower() for ax in legacy_run.result.figure.axes)

    # 2. Few runs, exact lower tail, and an opt-in residual panel.
    load("runs_curved", CURVED)

    def enable_runs(dialog):
        prepare(dialog, ["Y"], runs=True, residuals=True)
        show_options(dialog)
        capture(dialog, "02-runs-options.png")

    runs_index_before_reload = len(app.runs)
    curved = run_dialog(enable_runs)
    curved_index = runs_index_before_reload
    assert app.runs[curved_index] is curved
    curved_metrics = _metrics(curved, "Runs test: All")
    assert curved_metrics["Status"] == "Available"
    assert curved_metrics["Observed runs"] == 3
    assert float(curved_metrics["Expected runs"]) == 7
    assert math.isclose(curved_metrics["p"], P_FEW, rel_tol=0, abs_tol=1e-15)
    assert curved_metrics["Reason"] == RUNS_REASON_IT
    assert "Replicate lack of fit: All" not in curved.result.tables
    _assert_residual_panel(curved, count=12, raw=False)
    show_sheet(curved_index, "Runs test: All")
    capture(root, "03-runs-results.png")
    app.show("graph", curved_index)
    capture(root, "04-residual-view.png")

    # 3. Many runs stay a large lower-tail probability.
    load("runs_alternating", ALTERNATING)

    def enable_many(dialog):
        prepare(dialog, ["Y"], runs=True)

    many = run_dialog(enable_many)
    many_metrics = _metrics(many, "Runs test: All")
    assert many_metrics["Status"] == "Available"
    assert many_metrics["Observed runs"] == 7
    assert math.isclose(many_metrics["p"], P_MANY, rel_tol=0, abs_tol=1e-12)
    lowered = many_metrics["Reason"].lower()
    assert "poche" not in lowered and "pochi" not in lowered and "few" not in lowered, many_metrics["Reason"]
    show_sheet(len(app.runs) - 1, "Runs test: All")
    capture(root, "05-many-runs.png")

    # 4. Repeated X: the fit stays, runs explains the repetition, lack of fit is available.
    load("replicates_curved", REPLICATE_CURVED)

    def enable_both(dialog):
        prepare(dialog, ["Y"], runs=True, replicates=True)

    both = run_dialog(enable_both)
    both_index = len(app.runs) - 1
    both_runs = _metrics(both, "Runs test: All")
    both_lof = _metrics(both, "Replicate lack of fit: All")
    assert "Parameters: All" in both.result.tables
    assert "Fit: All" in both.result.tables
    assert "Residuals: All" in both.result.tables
    assert abs(float(both.result.tables["Fit: All"].loc["Residual SS", "Value"]) - 52) < 1e-6
    slope = float(both.result.tables["Parameters: All"].loc["Slope", "Estimate"])
    intercept = float(both.result.tables["Parameters: All"].loc["Intercept", "Estimate"])
    assert abs(slope - 4) < 1e-6 and abs(intercept) < 1e-6, (slope, intercept)
    assert both_runs["Status"] == "Not available" and both_runs["p"] is None
    assert "repliche" in both_runs["Reason"].lower(), both_runs["Reason"]
    assert both_lof["Status"] == "Available"
    assert math.isclose(float(both_lof["F"]), 14, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(float(both_lof["p"]), P_LOF, rel_tol=1e-9, abs_tol=0)
    show_sheet(both_index, "Replicate lack of fit: All")
    capture(root, "06-replicate-results.png")
    show_sheet(both_index, "Runs test: All")
    capture(root, "07-runs-unavailable.png")

    # 5. Unsorted X keeps the fit and the source order.
    load("unsorted_x", UNSORTED)

    def enable_unsorted(dialog):
        prepare(dialog, ["Y"], runs=True, residuals=True)

    unsorted = run_dialog(enable_unsorted)
    unsorted_metrics = _metrics(unsorted, "Runs test: All")
    assert unsorted_metrics["Status"] == "Not available" and unsorted_metrics["p"] is None
    assert "Riordina" in unsorted_metrics["Reason"], unsorted_metrics["Reason"]
    assert "Parameters: All" in unsorted.result.tables
    assert "Fit: All" in unsorted.result.tables
    xs = unsorted.result.tables["Residuals: All"]["X"].tolist()
    assert xs[:2] == [1, 0] or xs[:2] == [1.0, 0.0], xs[:2]
    assert xs != sorted(xs)
    _assert_residual_panel(unsorted, count=12, raw=False)
    show_sheet(len(app.runs) - 1, "Runs test: All")
    capture(root, "08-unsorted.png")

    # 6. A weighted test stays in the dialog. Residual view alone is allowed.
    app.show("data", "runs_curved")
    before = len(app.runs)

    def reject_weight(dialog):
        prepare(dialog, ["Y"], runs=True, replicates=True, weighting="1/Y²")
        invalid(dialog, RUNS, ("Runs test", "senza pesi"))
        show_options(dialog)
        capture(dialog, "09-weighting-error.png")

    drive(reject_weight)
    app.choose_analysis()
    assert len(app.runs) == before

    def weighted_view(dialog):
        prepare(dialog, ["Y"], residuals=True, weighting="1/Y²")

    weighted = run_dialog(weighted_view)
    assert weighted.options["Weighting"] == "1/Y²"
    assert weighted.options[RESIDUAL_VIEW] is True
    assert weighted.options[RUNS] is False and weighted.options[REPLICATES] is False
    assert not any(name.startswith("Runs test") or name.startswith("Replicate lack of fit")
                   for name in weighted.result.tables)
    _assert_residual_panel(weighted, count=12, raw=True)
    app.show("graph", len(app.runs) - 1)
    capture(root, "10-weighted-residuals.png")

    # 7. One ordered group and one reversed group stay separate. Two responses keep the classic layout.
    mixed_rows = ["X,Y,Group"]
    mixed_rows.extend(f"{x},{y},ordered" for x, y in CURVED_PAIRS)
    mixed_rows.extend(f"{x},{y},unsorted" for x, y in reversed(CURVED_PAIRS))
    load("mixed_groups", "\n".join(mixed_rows) + "\n")

    def enable_mixed(dialog):
        prepare(dialog, ["Y"], ["Group"], runs=True)

    mixed = run_dialog(enable_mixed)
    assert _metrics(mixed, "Runs test: ordered")["Status"] == "Available"
    assert math.isclose(_metrics(mixed, "Runs test: ordered")["p"], P_FEW, rel_tol=0, abs_tol=1e-15)
    unsorted_group = _metrics(mixed, "Runs test: unsorted")
    assert unsorted_group["Status"] == "Not available" and "Riordina" in unsorted_group["Reason"]
    assert "Parameters: ordered" in mixed.result.tables and "Parameters: unsorted" in mixed.result.tables
    reversed_x = mixed.result.tables["Residuals: unsorted"]["X"].tolist()
    assert reversed_x[0] == 11 or reversed_x[0] == 11.0
    assert reversed_x != sorted(reversed_x)
    show_sheet(len(app.runs) - 1, "Runs test: unsorted")
    capture(root, "11-mixed-groups.png")

    paired_rows = ["X,Y,Z"]
    paired_rows.extend(f"{x},{y},{y + 1}" for x, y in CURVED_PAIRS)
    load("two_responses", "\n".join(paired_rows) + "\n")

    def enable_two(dialog):
        prepare(dialog, ["Y", "Z"], residuals=True)

    paired = run_dialog(enable_two)
    assert len(paired.result.figure.axes) >= 4, len(paired.result.figure.axes)
    titles = {ax.get_title() for ax in paired.result.figure.axes}
    assert {"Y", "Z"} <= titles, titles
    assert "Y" in set(paired.result.tables["Parameters"]["Response variable"])
    assert "Z" in set(paired.result.tables["Parameters"]["Response variable"])
    assert any("resid" in ax.get_ylabel().lower() for ax in paired.result.figure.axes)
    app.show("graph", len(app.runs) - 1)
    capture(root, "12-multiple-responses.png")

    # A recipe saved before these keys existed gains none of them.
    legacy_project = directory / "v061-fit.alab"
    frame = pd.read_csv(directory / "legacy.csv")
    save_project(legacy_project, {"legacy": Dataset(frame, analyses=[(
        METHOD, {"X": "X", "Y": "Y", "Model": "Straight line"})])})
    side = app.add_project()
    assert side is not None
    app.import_file(legacy_project)
    app.open_sheet(("result", 0))
    wait()
    old = app.runs[0]
    assert RUNS not in old.options and REPLICATES not in old.options and RESIDUAL_VIEW not in old.options
    assert list(old.result.tables) == ["Parameters: All", "Fit: All", "Residuals: All"]
    assert len(old.result.figure.axes) == 1
    assert app.switch_project(side)
    assert not app.dirty
    app.close_project()
    assert app.active_project == project

    # 8. Save, reopen, export, then show the same recipe in English.
    saved_path = directory / "fit-quality.alab"
    app.path = saved_path
    assert app.save()
    blob = saved_path.read_text(encoding="utf-8")
    saved = json.loads(blob)
    recipe = next(options for table in saved["tables"] if table["title"] == "runs_curved"
                  for method, options in table["analyses"]
                  if options.get(RUNS) is True and options.get(RESIDUAL_VIEW) is True
                  and options.get("Weighting", "Unweighted") == "Unweighted")
    assert recipe[REPLICATES] is False
    assert "Residui contro X" not in blob and "Residui rispetto a X" not in blob and "analysis.fit" not in blob
    app.import_file(saved_path)
    reopened_index = next(i for i, run in enumerate(app.runs)
                          if run.title == "runs_curved" and run.options.get(RUNS) is True
                          and run.options.get(RESIDUAL_VIEW) is True
                          and run.options.get("Weighting", "Unweighted") == "Unweighted")
    app.open_sheet(("result", reopened_index))
    wait()
    reopened = app.runs[reopened_index]
    assert reopened.options[RUNS] is True and reopened.options[RESIDUAL_VIEW] is True
    assert _metrics(reopened, "Runs test: All")["Reason"] == RUNS_REASON_IT
    assert math.isclose(_metrics(reopened, "Runs test: All")["p"], P_FEW, rel_tol=0, abs_tol=1e-15)
    app.show("graph", reopened_index)
    for suffix in ("png", "svg", "pdf"):
        target = directory / f"residual-view.{suffix}"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "residual-view.svg").read_bytes()
    assert (directory / "residual-view.pdf").read_bytes().startswith(b"%PDF-")
    show_sheet(reopened_index, "Runs test: All")
    csv_path = directory / "runs-test.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    reason = exported.loc[exported["Metric"] == "Reason", "Value"].iloc[0]
    assert reason == RUNS_REASON_IT and "…" not in reason

    def english(dialog):
        assert dialog.field_rows[RUNS][0].cget("text") == "Runs test"
        assert dialog.field_rows[REPLICATES][0].cget("text") == "Replicate lack of fit"
        assert dialog.field_rows[RESIDUAL_VIEW][0].cget("text") == "Residuals versus X"
        assert dialog.controls[RUNS][1].get() is True
        assert dialog.controls[RESIDUAL_VIEW][1].get() is True
        shown = note(dialog)
        assert "unweighted" in shown.lower() and "raw residuals" in shown.lower(), shown
        kept = {RUNS: dialog.controls[RUNS][1].get(), REPLICATES: dialog.controls[REPLICATES][1].get(),
                RESIDUAL_VIEW: dialog.controls[RESIDUAL_VIEW][1].get(),
                "Weighting": dialog.controls["Weighting"][1].get(),
                "Model": dialog.controls["Model"][1].get()}
        dialog._smoke_kept = kept
        show_options(dialog)

    set_language("en")
    app.show("result", reopened_index)
    drive(english)
    app.edit_analysis()
    wait()
    edited = app.runs[reopened_index]
    assert edited.options[RUNS] is True and edited.options[RESIDUAL_VIEW] is True
    assert edited.options[REPLICATES] is False
    assert edited.options["Weighting"] == "Unweighted"
    assert set(edited.options) == set(reopened.options)
    english_metrics = _metrics(edited, "Runs test: All")
    assert english_metrics["Reason"] == RUNS_REASON_EN
    assert math.isclose(english_metrics["p"], P_FEW, rel_tol=0, abs_tol=1e-15)
    assert "analysis.fit" not in english_metrics["Reason"]
    show_sheet(reopened_index, "Runs test: All")
    capture(root, "13-reopened-en.png")

    # Integration: the same fit supplies the band, runs test and residual view.
    app.show("data", "runs_curved")
    def combined(dialog):
        prepare(dialog, ["Y"], runs=True, residuals=True)
        dialog.controls["Band"][1].set("Confidence (mean)")
        dialog.update_idletasks()
        assert note(dialog) == tr("analysis.fit.note.diagnostics")
        show_options(dialog)
        capture(dialog, "14-bands-and-quality-options.png")
    combined_run = run_dialog(combined)
    assert "Band: All" in combined_run.result.tables
    assert "Runs test: All" in combined_run.result.tables
    assert math.isclose(_metrics(combined_run, "Runs test: All")["p"], P_FEW, abs_tol=1e-15)
    _assert_residual_panel(combined_run, count=12, raw=False)
    assert len(combined_run.result.figure.axes) == 2
    app.show("graph", len(app.runs) - 1)
    wait()
    capture(root, "14-bands-and-quality.png")


def _metrics(run, title):
    return run.result.tables[title]["Value"].to_dict()


def _assert_residual_panel(run, *, count, raw):
    panels = [ax for ax in run.result.figure.axes if "resid" in ax.get_ylabel().lower()]
    assert panels, [ax.get_ylabel() for ax in run.result.figure.axes]
    if raw:
        assert any("raw" in ax.get_ylabel().lower() for ax in panels)
    else:
        assert all("raw" not in ax.get_ylabel().lower() for ax in panels)
    assert any(len(collection.get_offsets()) == count for ax in panels for collection in ax.collections)
    assert any(len(line.get_ydata()) and all(abs(float(y)) < 1e-12 for y in line.get_ydata())
               for ax in panels for line in ax.lines)
