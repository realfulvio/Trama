"""Desktop smoke check for the Lognormal t-test (0.70), driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_lognormal_tests` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=lognormal-tests python tramastat.py --smoke DIR``.

Synthetic data only. Expected values are written here with NumPy and SciPy from the textbook formulas
(t tests on the log values), independent of the module under test.
"""
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import i18n
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .lognormal_tests import LOGNORMAL

DATA, EXTREME, FLAT, BAD, OLD = "Lognormal data", "Extreme ratios", "Constant ratios", "Zero cell", "Legacy"
BEFORE = [3., 5, 8, 11, 15, 2.5, np.nan]
AFTER = [6.3, 9.6, 17.2, 20.9, 32.0, np.nan, 7.0]
FRAMES = {
    DATA: pd.DataFrame({"Before": BEFORE, "After": AFTER}),
    EXTREME: pd.DataFrame({"Before": [1e300, 2e300, 4e300], "After": [1e-300, 1e-300, 1e-300]}),
    FLAT: pd.DataFrame({"Before": [2., 2, 2, 2], "After": [1., 1, 1, 1]}),
    BAD: pd.DataFrame({"Before": [3., 5, 0.0, 11], "After": [6.3, 9.6, 17.2, 20.9]}),
}
LEGACY = ("Paired t-test (columns)", {"First": "Before", "Second": "After"})


def paired(first, second, base=10., reverse=False, null=1., level=95., alternative="Two-sided"):
    """Independent reference for a paired test: returns (ratio, lower, upper, t, df, p, mean log, SE log)."""
    first, second = np.asarray(first, float), np.asarray(second, float)
    keep = ~np.isnan(first) & ~np.isnan(second)
    d = np.log(first[keep]) - np.log(second[keep])
    d = -d if reverse else d
    n = len(d)
    se = d.std(ddof=1) / np.sqrt(n)
    t = (d.mean() - np.log(null)) / se
    p = {"Two-sided": 2 * stats.t.sf(abs(t), n - 1), "Greater": stats.t.sf(t, n - 1),
         "Less": stats.t.cdf(t, n - 1)}[alternative]
    half = stats.t.ppf((1 + level / 100) / 2, n - 1) * se
    return (np.exp(d.mean()), np.exp(d.mean() - half), np.exp(d.mean() + half), t, n - 1, p,
            d.mean() / np.log(base), se / np.log(base))


def welch(first, second):
    a = np.log(np.asarray(first, float)[~np.isnan(first)])
    b = np.log(np.asarray(second, float)[~np.isnan(second)])
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    t = (a.mean() - b.mean()) / np.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    return t, df, 2 * stats.t.sf(abs(t), df), np.exp(a.mean() - b.mean())


def check_lognormal_tests(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "lognormal-tests"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    path = directory / "lognormal-tests.alab"
    legacy = Dataset(FRAMES[DATA].copy())
    legacy.analyses.append((LEGACY[0], dict(LEGACY[1])))
    save_project(path, {DATA: legacy, EXTREME: Dataset(FRAMES[EXTREME].copy()), FLAT: Dataset(FRAMES[FLAT].copy()),
                        BAD: Dataset(FRAMES[BAD].copy())})
    app.import_file(path)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def rejected(dialog, field, contains, shot_name=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert field in message and contains in message, message
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
        """Run Analysis and the field notebook lie inside the screen at the current size."""
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

    def test_row(index):
        return table(index, "Lognormal test").iloc[0]

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == LOGNORMAL and app.runs[index].title == title
        return index

    # 0. A recipe saved before this method existed keeps its sheet.
    app.open_sheet(("result", 0))
    wait()
    assert list(app.runs[0].result.tables) == ["t-test"] and app.runs[0].method == LEGACY[0]

    # 1. Dialog defaults, inactive fields, an invalid value on its own field, the correction in the same dialog.
    def first_dialog(dialog):
        tools.pick_method(dialog, LOGNORMAL)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Data", "Test and graph"]
        assert controls["Design"][1].get() == "Paired" and controls["Report ratio"][1].get() == "First / Second"
        assert controls["Null ratio"][1].get() == "1.0" and controls["Confidence level (%)"][1].get() == "95.0"
        assert controls["Alternative"][1].get() == "Two-sided" and controls["Log base"][1].get() == "10"
        assert controls["Graph"][1].get() == "Ratio estimation" and controls["Pairing correlation"][1].get() is True
        assert placed(dialog, "Second") and placed(dialog, "Pairing correlation")
        assert not placed(dialog, "Hypothetical geometric mean")
        controls["First"][1].set("Before")
        controls["Second"][1].set("After")
        dialog.fields.select(0)
        reachable(dialog)
        dialog.fields.select(0)
        shot(dialog, "window-lognormal-dialog" + suffix + ".png")
        # One-sample: Second and the pairing correlation are inactive, the reference is active.
        controls["Design"][1].set("One-sample")
        dialog.update()
        assert not placed(dialog, "Second") and not placed(dialog, "Pairing correlation")
        assert placed(dialog, "Hypothetical geometric mean")
        controls["Hypothetical geometric mean"][1].set("-2")
        rejected(dialog, "Hypothetical geometric mean", "positive")
        controls["Hypothetical geometric mean"][1].set("abc")
        rejected(dialog, "Hypothetical geometric mean", "must be a number")
        controls["Design"][1].set("Paired")
        dialog.update()
        # Hidden values are not validated: a bad reference does not stop a paired run.
        assert not placed(dialog, "Hypothetical geometric mean")
        assert dialog.validate() is True
        # Same column twice, a null ratio of zero and a level of 100 each name their own field.
        controls["Second"][1].set("Before")
        rejected(dialog, "Second", "different columns")
        controls["Second"][1].set("After")
        controls["Null ratio"][1].set("0")
        rejected(dialog, "Null ratio", "positive", "window-lognormal-error.png")
        controls["Confidence level (%)"][1].set("100")
        controls["Null ratio"][1].set("0,5")
        rejected(dialog, "Confidence level (%)", "less than 100")
        controls["Graph"][1].set("Log ratios")
        controls["Design"][1].set("Welch")
        dialog.update()
        assert not placed(dialog, "Pairing correlation")
        controls["Confidence level (%)"][1].set("95")
        rejected(dialog, "Graph", "Paired and One-sample")
        # The corrected values stay in the same dialog; Run Analysis is still reachable.
        assert controls["Null ratio"][1].get() == "0,5" and controls["Design"][1].get() == "Welch"
        controls["Design"][1].set("Paired")
        controls["Graph"][1].set("Ratio estimation")
        controls["Null ratio"][1].set("1")
        dialog.update()
        reachable(dialog)

    index = analyse_with(first_dialog, DATA)
    options = app.runs[index].options
    assert options["Design"] == "Paired" and options["Log base"] == "10" and options["Graph"] == "Ratio estimation"
    assert "Hypothetical geometric mean" not in options and options["Null ratio"] == 1.0
    assert options["Pairing correlation"] is True and options["Confidence level (%)"] == 95.0

    # 2. Numbers against the independent reference, the three sheets and the figure.
    ratio, low, high, t, df, p, mean, se = paired(BEFORE, AFTER)
    result = test_row(index)
    assert (result["N first"], result["N second"], result["df"], result["Status"]) == (5, 5, df, "OK")
    np.testing.assert_allclose([result["Geometric ratio"], result["Lower"], result["Upper"], result["t"], result["p"],
                                result["Mean log ratio"], result["SE log ratio"]],
                               [ratio, low, high, t, p, mean, se], rtol=1e-9)
    ratios = table(index, "Paired ratios")
    assert ratios["Source row"].tolist() == [0, 1, 2, 3, 4], ratios
    assert set(app.runs[index].result.tables) == {"Lognormal test", "Log observations", "Paired ratios", "Settings"}
    assert "Pearson r (log values)" in table(index, "Settings")["Value"]
    app.show("result", index)
    app.result_tabs.select(0)
    shot(root, "window-lognormal-result" + suffix + ".png")
    app.show("graph", index)
    root.update()
    axes = app.runs[index].result.figure.axes[0]
    assert axes.get_xscale() == "log" and "log10" in axes.get_title() and "Before / After" in axes.get_title()
    shot(root, "window-lognormal-graph" + suffix + ".png")

    # 3. Result and graph stay open: edit one source cell and exclude another; both recalculate.
    app.show("data", DATA)
    app.edit_cell(2, 0, "9")
    wait()
    edited = list(BEFORE)
    edited[2] = 9.
    np.testing.assert_allclose(test_row(index)["t"], paired(edited, AFTER)[3], rtol=1e-9)
    app.show("data", DATA)
    app.current_grid.select((3, 1))
    app.toggle_exclusion()
    wait()
    masked = list(AFTER)
    masked[3] = np.nan
    expected = paired(edited, masked)
    result = test_row(index)
    assert result["N first"] == 4, result
    np.testing.assert_allclose([result["Geometric ratio"], result["t"], result["p"]],
                               [expected[0], expected[3], expected[5]], rtol=1e-9)
    assert table(index, "Paired ratios")["Source row"].tolist() == [0, 1, 2, 4]
    assert table(index, "Log observations")["Source row"].tolist() == [0, 1, 2, 4] * 2
    app.show("graph", index)
    root.update()

    # 4. Inspector: Apply changes the style, Cancel restores the confirmed one; Format Graph sets the title.
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn series"
    panel.select_group(panel.elements[0]["key"])
    panel.vars["element:color"].set("#9b4174")
    widget = panel.fields["color"]["widget"]
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    confirmed = app.runs[index].style
    assert confirmed and "#9b4174" in str(confirmed), confirmed
    panel.vars["element:color"].set("#117733")
    widget.event_generate("<Return>")
    root.update()
    assert panel.has_draft
    panel.cancel()
    root.update()
    assert app.inspector is None and app.runs[index].style == confirmed
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Ratio of geometric means"))
    app.format_graph()
    wait()
    assert app.runs[index].result.figure.axes[0].get_title() == "Ratio of geometric means"
    app.show("graph", index)
    root.update()

    # 5. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure.
    app.show("result", index)
    for position, name in enumerate(("Lognormal test", "Log observations", "Paired ratios", "Settings")):
        app.result_tabs.select(position)
        target = out / f"lognormal-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Paired ratios":
            assert list(exported.columns) == ["Source row", "First", "Second", "Log ratio", "Ratio"]
            assert exported["Source row"].tolist() == [0, 1, 2, 4]
        if name == "Lognormal test":
            assert exported.loc[0, "Status"] == "OK"
    app.show("graph", index)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"lognormal-ratio.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension

    # 6. Italian: captions and choices on screen, canonical keys and values in the recipe.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, LOGNORMAL)
        captions = {name: dialog.field_rows[name][0].cget("text")
                    for name in ("Design", "First", "Second", "Report ratio", "Null ratio", "Confidence level (%)",
                                 "Alternative", "Log base", "Graph", "Pairing correlation")}
        assert captions == {"Design": "Disegno", "First": "Prima colonna", "Second": "Seconda colonna",
                            "Report ratio": "Rapporto riportato", "Null ratio": "Rapporto nullo",
                            "Confidence level (%)": "Livello di confidenza (%)", "Alternative": "Ipotesi alternativa",
                            "Log base": "Base del logaritmo", "Graph": "Grafico",
                            "Pairing correlation": "Correlazione di appaiamento"}, captions
        tabs = [dialog.fields.tab(i, "text") for i in range(2)]
        assert tabs == ["Dati", "Test e grafico"], tabs
        design = dialog.field_rows["Design"][1]
        assert design.get() == "Appaiato" and dialog.controls["Design"][1].get() == "Paired", design.get()
        shown = {name: list(dialog.field_rows[name][1].cget("values"))
                 for name in ("Design", "Report ratio", "Alternative", "Log base", "Graph")}
        assert shown == {"Design": ["Appaiato", "Welch", "Student", "Un campione"],
                         "Report ratio": ["Primo / Secondo", "Secondo / Primo"],
                         "Alternative": ["Bilaterale", "Maggiore", "Minore"], "Log base": ["10", "e (naturale)"],
                         "Graph": ["Stima del rapporto", "Osservazioni logaritmiche", "Rapporti logaritmici",
                                   "Nessuno"]}, shown
        design.set("Welch")
        dialog.update()
        assert dialog.controls["Design"][1].get() == "Welch" and not placed(dialog, "Pairing correlation"), (
            dialog.controls["Design"][1].get(), placed(dialog, "Pairing correlation"))
        dialog.controls["First"][1].set("Before")
        dialog.controls["Second"][1].set("After")
        dialog.field_rows["Report ratio"][1].set("Secondo / Primo")
        dialog.field_rows["Alternative"][1].set("Maggiore")
        dialog.field_rows["Log base"][1].set("e (naturale)")
        dialog.field_rows["Graph"][1].set("Osservazioni logaritmiche")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-lognormal-it" + suffix + ".png")
        chosen = {name: dialog.controls[name][1].get() for name in ("Report ratio", "Alternative", "Log base", "Graph")}
        assert chosen == {"Report ratio": "Second / First", "Alternative": "Greater", "Log base": "e",
                          "Graph": "Log observations"}, chosen

    def traced(action):
        def run(dialog):
            import traceback
            try:
                action(dialog)
            except Exception:
                (out / "trace.txt").write_text(traceback.format_exc(), encoding="utf-8")
                raise
        return run

    try:
        i18n.set_language("it")
        app.show("data", DATA)
        tools.drive_dialog(tools.AnalysisDialog, traced(italian))
        app.choose_analysis()
        wait()
        welch_index = len(app.runs) - 1
        saved = app.runs[welch_index].options
        assert (saved["Design"], saved["Report ratio"], saved["Alternative"], saved["Log base"], saved["Graph"]) == (
            "Welch", "Second / First", "Greater", "e", "Log observations"), saved
        assert "Pairing correlation" not in saved and "Hypothetical geometric mean" not in saved
        # The excluded After cell (row 3) is no longer in the sample: recompute on the remaining ones.
        t_value, df_value, two_sided, ratio_w = welch(edited, masked)
        result = test_row(welch_index)
        np.testing.assert_allclose([result["t"], result["df"], result["Geometric ratio"]],
                                   [-t_value, df_value, 1 / ratio_w], rtol=1e-9)
        np.testing.assert_allclose(result["p"], stats.t.sf(-t_value, df_value), rtol=1e-9)
        assert (result["N first"], result["N second"]) == (6, 5)
        app.show("graph", welch_index)
        root.update()
        shot(root, "window-lognormal-it-result" + suffix + ".png")
        recipe = dict(saved)
        i18n.set_language("en")

        def english_again(dialog):
            shown = [dialog.field_rows[name][1].get() for name in ("Design", "Log base", "Alternative", "Graph")]
            assert shown == ["Welch", "e (natural)", "Greater", "Log observations"], shown
            canonical = [dialog.controls[name][1].get() for name in ("Design", "Log base", "Alternative", "Graph")]
            assert canonical == ["Welch", "e", "Greater", "Log observations"], canonical

        app.show("result", welch_index)
        tools.drive_dialog(tools.AnalysisDialog, english_again)
        app.edit_analysis()
        wait()
        assert app.runs[welch_index].options == recipe
    finally:
        i18n.set_language(original_language)

    # 7. One-sample with Log ratios, then Student with an unsupported graph that stays in the dialog.
    def one_sample(dialog):
        tools.pick_method(dialog, LOGNORMAL)
        dialog.controls["Design"][1].set("One-sample")
        dialog.controls["First"][1].set("After")
        dialog.controls["Hypothetical geometric mean"][1].set("10")
        dialog.controls["Graph"][1].set("Log ratios")
        dialog.controls["Log base"][1].set("e")

    one_index = analyse_with(one_sample, DATA)
    values = np.log([6.3, 9.6, 17.2, 32.0, 7.0])           # the excluded 20.9 is out
    t_value, p_value = stats.ttest_1samp(values, np.log(10.))
    result = test_row(one_index)
    np.testing.assert_allclose([result["t"], result["p"], result["Geometric ratio"]],
                               [t_value, p_value, np.exp(values.mean()) / 10], rtol=1e-9)
    assert (result["N first"], result["N second"]) == (5, 0) and "Paired ratios" not in app.runs[one_index].result.tables
    assert "Second" not in app.runs[one_index].options
    app.show("graph", one_index)
    root.update()
    shot(root, "window-lognormal-one-sample" + suffix + ".png")

    # 8. Edge cases: a ratio beyond the floating-point range and ratios that are exactly constant.
    def extreme(dialog):
        tools.pick_method(dialog, LOGNORMAL)
        dialog.controls["First"][1].set("Before")
        dialog.controls["Second"][1].set("After")

    extreme_index = analyse_with(extreme, EXTREME)
    result = test_row(extreme_index)
    assert result["Status"] == "Ratio overflow" and np.isnan(result["Geometric ratio"]) and result["Reason"]
    np.testing.assert_allclose(result["Mean log ratio"], 600.3010299956638, rtol=1e-9)
    app.show("graph", extreme_index)
    root.update()
    annotation = " ".join(t.get_text() for t in app.runs[extreme_index].result.figure.axes[0].texts)
    assert "outside the numeric range" in annotation and "600.301" in annotation, annotation
    shot(root, "window-lognormal-limit" + suffix + ".png")
    flat_index = analyse_with(extreme, FLAT)
    result = test_row(flat_index)
    assert result["Status"] == "Inference unavailable" and result["Geometric ratio"] == 2.0 and np.isnan(result["p"])
    app.show("result", flat_index)
    app.result_tabs.select(0)
    shot(root, "window-lognormal-flat" + suffix + ".png")

    # 9. A non-positive value on a used row names its column and keeps the dialog open.
    def zero_cell(dialog):
        tools.pick_method(dialog, LOGNORMAL)
        dialog.controls["First"][1].set("Before")
        dialog.controls["Second"][1].set("After")
        message = rejected(dialog, "First", "Source row 2", "window-lognormal-zero.png")
        assert "positive" in message, message
        dialog.controls["Design"][1].set("One-sample")
        dialog.controls["First"][1].set("After")
        dialog.update()
        assert dialog.validate() is True

    app.show("data", BAD)
    tools.drive_dialog(tools.AnalysisDialog, zero_cell)
    app.choose_analysis()
    wait()
    assert test_row(len(app.runs) - 1)["N first"] == 4

    # 10. Save, reopen and open the graph before the worksheet.
    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                for run in app.runs if run.method == LOGNORMAL and run.result is not None}
    assert len(expected) == 6, sorted(expected)
    app.path = directory / "lognormal-tests-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == LOGNORMAL:
            app.open_sheet(("graph", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, tables) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    key = next(k for k in expected if k[0] == DATA and expected[k][0]["Design"] == "Paired")
    reopened_index = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert reopened[key].style and "#9b4174" in str(reopened[key].style)
    app.show("graph", reopened_index)
    root.update()
    shot(root, "window-lognormal-reopened" + suffix + ".png")

    # 11. Use Result as Data from the new sheets keeps the source rows.
    before_tables = set(app.tables)
    for position in (1, 2):
        app.show("result", reopened_index)
        app.result_tabs.select(position)
        app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 2, created
    assert any(list(f.columns) == ["Source row", "Sample", "Value", "Log value"] and len(f) == 8
               for f in created.values()), {k: list(v.columns) for k, v in created.items()}
    assert any(list(f.columns) == ["Source row", "First", "Second", "Log ratio", "Ratio"] and len(f) == 4
               for f in created.values())
    wait()
    assert app.pending is None and not errors, errors
