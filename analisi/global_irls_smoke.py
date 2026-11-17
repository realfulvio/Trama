"""Desktop smoke check for global fits with observed-Y and fitted-curve weights (0.60).

``tramastat.py --smoke`` calls :func:`check_global_irls` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=global-irls python tramastat.py --smoke DIR``.

Synthetic data only. The expected numbers come from closed-form weighted least squares computed here
with numpy (one design matrix, the fitted modes iterated to their fixed point), independent of the
optimizer the application uses.
"""
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import fit_weights as fw
from . import i18n
from .data import Dataset, save_project
from .presentation import Layout
from .workbench import analyse

METHOD = "Global nonlinear regression"
SHEET, WIDE, OLD, MANY = "Global weights", "Wide curves", "Legacy global", "Many curves"
ZERO = "Zero prediction"
CHOICES = fw.GLOBAL_WEIGHTINGS
RNG = np.random.default_rng(20)
INTERCEPTS = {"A": 2., "B": 9., "C": 20.}
LONG_X = np.tile(np.arange(1., 7.), 3)
LONG_Y = np.round(1.5 * LONG_X + np.repeat(list(INTERCEPTS.values()), 6) + .35 * RNG.standard_normal(18), 3)
FRAME = pd.DataFrame({
    "X": [*LONG_X, None], "Y": [*LONG_Y, 5.], "Series": [*np.repeat(list("ABC"), 6), "A"],
    "SD": [np.nan] * 19,  # a column left selected but inactive must not block any weighting
})
OLD_FRAME = FRAME.iloc[:18].reset_index(drop=True)
BASE = {"Input format": "Long table", "X": "X", "Y": "Y", "Series": "Series", "Model": "Straight line",
        "Shared parameters": ["Slope"]}
OLD_RECIPES = [
    (METHOD, dict(BASE)),  # saved before Weighting was a global choice
    (METHOD, {**BASE, "Weighting": "Unweighted"}),
]
WIDE_FRAME = pd.DataFrame({"Dose": np.arange(1., 8.)})
for _name, _intercept in (("A", 2.), ("B", 9.)):
    for _replicate in (1, 2):
        WIDE_FRAME[f"{_name} [{_replicate}]"] = np.round(
            _intercept + 1.5 * WIDE_FRAME["Dose"] + 1 + .3 * RNG.standard_normal(7), 3)
CONCENTRATION = np.geomspace(.1, 40., 30)
MANY_FRAME = pd.concat([
    pd.DataFrame({"Conc": CONCENTRATION, "Rate": np.round(
        (8 + 2 * k) * CONCENTRATION / (3. + CONCENTRATION) * (1 + .05 * RNG.standard_normal(30)), 4), "Enzyme": f"E{k}"})
    for k in range(10)], ignore_index=True)


# Michaelis–Menten passes through zero at X = 0, so the fitted modes stop with an error on Weighting.
ZERO_FRAME = pd.DataFrame({
    "X": [0., .5, 1., 2., 4., 8.] * 2,
    "Y": [.03, .99, 1.6866666666666668, 2.48, 3.3733333333333335, 3.99,
          .03, 1.59, 2.6866666666666665, 3.98, 5.373333333333333, 6.390000000000001],
    "Series": ["A"] * 6 + ["B"] * 6,
})
ZERO_OPTIONS = {"Input format": "Long table", "X": "X", "Y": "Y", "Series": "Series", "Model": "Michaelis–Menten",
                "Shared parameters": ["Km"], "Weighting": "1/Yfit²"}


def power(label):
    return 1.0 if "²" in label else 0.5


def reference(x, y, series, label, *, fixed=None):
    """Joint straight line with one common slope and one intercept per series, weighted by one scale vector.

    ``fixed`` maps series to intercepts held constant. Returns (slope, intercepts, weighted SS, scales)."""
    x, y, series = np.asarray(x, float), np.asarray(y, float), np.asarray(series)
    fixed = fixed or {}
    levels = list(dict.fromkeys(series))
    free = [level for level in levels if level not in fixed]
    design = np.column_stack([x, *[(series == level).astype(float) for level in free]])
    offset = sum(((series == level) * fixed[level] for level in fixed), np.zeros(len(y)))
    target = y - offset
    beta = np.linalg.lstsq(design, target, rcond=None)[0]
    scale = np.ones(len(y))
    for _ in range(500):
        if label in fw.OBSERVED_WEIGHTINGS:
            scale = np.abs(y) ** power(label)
        elif label in fw.FITTED_WEIGHTINGS:
            scale = np.abs(design @ beta + offset) ** power(label)
        update = np.linalg.lstsq(design / scale[:, None], target / scale, rcond=None)[0]
        done = np.allclose(update, beta, rtol=1e-12, atol=0)
        beta = update
        if label not in fw.FITTED_WEIGHTINGS or done:
            break
    residual = target - design @ beta
    return beta[0], dict(zip(free, beta[1:])), float(np.sum((residual / scale) ** 2)), scale


def check_global_irls(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "global-irls"
    out.mkdir(exist_ok=True)
    path = directory / "global-irls.alab"

    old = Dataset(OLD_FRAME.copy())
    old.analyses.extend((method, dict(options)) for method, options in OLD_RECIPES)
    save_project(path, {SHEET: Dataset(FRAME.copy()), WIDE: Dataset(WIDE_FRAME.copy()),
                        MANY: Dataset(MANY_FRAME.copy()), OLD: old, ZERO: Dataset(ZERO_FRAME.copy())})
    app.import_file(path)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot_name=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            shot(dialog, shot_name)

    def drive(action, *, accept):
        """Like tools.drive_dialog, but the dialog can also be cancelled."""
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found

        def enter():
            dialog = find(root)
            if dialog is None:
                errors.append("AnalysisDialog did not open")
                return
            try:
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(str(error))
                dialog.cancel()

        root.after(200, enter)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def joint(index):
        return table(index, "Joint fit")["Value"]

    def parameter(index, scope, group, name):
        frame = table(index, "Parameters")
        row = frame[(frame["Scope"] == scope) & (frame["Parameter"] == name)
                    & (frame["Group"].isna() if group is None else frame["Group"] == group)]
        assert len(row) == 1, (scope, group, name)
        return float(row["Estimate"].iloc[0])

    def check_against(index, x, y, series, label, rtol=2e-5, *, fixed=None):
        slope, intercepts, weighted_ss, _ = reference(x, y, series, label, fixed=fixed)
        assert abs(parameter(index, "Shared", None, "Slope") - slope) < rtol * abs(slope), (label, slope)
        for level, value in intercepts.items():
            found = parameter(index, "Local", level, "Intercept")
            assert abs(found - value) < rtol * max(1., abs(value)), (label, level, found, value)
        found_ss = float(joint(index)["Weighted residual SS"])
        assert abs(found_ss - weighted_ss) < rtol * weighted_ss, (label, found_ss, weighted_ss)

    def sheet_columns():
        return list(app.tables[SHEET].raw.columns)

    # 1. Recipes saved by earlier versions keep their results and show no new diagnostics.
    positions = [i for i, run in enumerate(app.runs) if run.title == OLD]
    assert len(positions) == 2, positions
    for position, (method, options) in zip(positions, OLD_RECIPES):
        app.open_sheet(("result", position))
        wait()
        assert app.runs[position].options == options, app.runs[position].options
        expected = analyse(method, OLD_FRAME, options)
        assert list(app.runs[position].result.tables) == list(expected.tables)
        for name, frame in expected.tables.items():
            pd.testing.assert_frame_equal(app.runs[position].result.tables[name], frame)
        assert "Weighting iterations" not in app.runs[position].result.tables["Joint fit"].index
        check_against(position, OLD_FRAME["X"], OLD_FRAME["Y"], OLD_FRAME["Series"], "Unweighted")

    # 2. A zero response is edited into the table. The observed modes name the Weighting field and stay
    #    in the dialog; 1/Yfit² accepts the zero, converges and gives the closed-form fixed point.
    app.show("data", SHEET)
    columns = sheet_columns()
    app.edit_cell(3, columns.index("Y"), "0")
    wait()
    zero_y = [*LONG_Y]
    zero_y[3] = 0.

    def new_fit(dialog):
        tools.pick_method(dialog, METHOD)
        assert dialog.controls["Input format"][1].get() == "Long table"
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.controls["Series"][1].set("Series")
        dialog.controls["Model"][1].set("Straight line")
        dialog.parameters.rows["Slope"][0].set("Shared")
        assert dialog.controls["Weighting"][1].get() == "Unweighted"
        assert tuple(dialog.field_rows["Weighting"][1].cget("values")) == CHOICES
        assert "equally" in dialog.weighting_note.cget("text")
        # The format and SD controls keep their usual visibility.
        assert placed(dialog, "SD column") and placed(dialog, "Y") and placed(dialog, "Series")
        assert not placed(dialog, "Y columns") and not placed(dialog, "Merge numbered replicates")
        dialog.controls["Weighting"][1].set("1/Y²")
        dialog.update()
        assert "relative distances" in dialog.weighting_note.cget("text")
        assert placed(dialog, "SD column")
        rejected(dialog, "Weighting", "window-global-irls-zero-error.png")
        dialog.controls["Weighting"][1].set("1/abs(Y)")
        rejected(dialog, "Weighting")
        dialog.controls["Weighting"][1].set("1/Yfit²")
        dialog.update()
        assert "Yfit" in dialog.weighting_note.cget("text") and "50" in dialog.weighting_note.cget("text")
        dialog.fields.select(dialog.field_rows["Weighting"][1].master)
        dialog.controls["Compare with independent fits"][1].set(True)
        shot(dialog, "window-global-irls-dialog.png")

    tools.drive_dialog(tools.AnalysisDialog, new_fit)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.options["Weighting"] == "1/Yfit²" and run.options["Shared parameters"] == ["Slope"], run.options
    check_against(index, LONG_X, zero_y, np.repeat(list("ABC"), 6), "1/Yfit²")
    report = joint(index)
    assert report["N"] == 18 and report["Weighting"] == "1/Yfit²"
    assert bool(report["Weighting converged"]) is True and report["Inference weights"] == "Final frozen weights"
    refits = int(report["Weighting iterations"])
    assert 1 <= refits <= fw.MAX_WEIGHT_REFITS, refits
    assert list(app.tables[SHEET].raw.columns) == list(FRAME.columns), "weights must not add worksheet columns"
    # The comparison sheet exists and its independent fits use the frozen weights of the main fit.
    assert "Shared vs independent" in app.runs[index].result.tables
    assert np.isfinite(float(table(index, "Shared vs independent")["Value"]["F"]))
    curve = table(index, "Fit curves")
    slope = parameter(index, "Shared", None, "Slope")
    for level in "ABC":
        rows = curve[curve["Series"] == level]
        assert np.allclose(rows["Predicted"], parameter(index, "Local", level, "Intercept") + slope * rows["X"],
                           rtol=1e-6, atol=1e-6)
    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index("Joint fit"))
    shot(root, "window-global-irls-result.png")
    app.show("graph", index)
    shot(root, "window-global-irls-graph.png")
    for suffix in ("png", "svg"):
        target = out / f"global-irls.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (out / "global-irls.svg").read_bytes()
    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index("Joint fit"))
    csv = out / "global-irls.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = csv.read_text(encoding="utf-8-sig")
    assert "Weighting iterations" in exported and "Final frozen weights" in exported, exported[:300]
    before = set(app.tables)
    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index("Joint fit"))
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1, added
    assert "Weighting iterations" in app.tables[added.pop()].raw.iloc[:, 0].astype(str).tolist()

    # 3. Editing: a cancelled change keeps the confirmed analysis; the zero still blocks 1/abs(Y).
    def change(dialog):
        dialog.controls["Weighting"][1].set("Unweighted")

    app.show("result", index)
    drive(change, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[index].options["Weighting"] == "1/Yfit²"
    check_against(index, LONG_X, zero_y, np.repeat(list("ABC"), 6), "1/Yfit²")

    def blocked(dialog):
        assert dialog.controls["Weighting"][1].get() == "1/Yfit²"
        dialog.controls["Weighting"][1].set("1/abs(Y)")
        rejected(dialog, "Weighting")
        dialog.controls["Weighting"][1].set("1/abs(Yfit)")

    drive(blocked, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[index].options["Weighting"] == "1/Yfit²"

    # 4. The cell recovers: the linked analysis recalculates on the worker; then 1/abs(Y) is accepted.
    app.show("data", SHEET)
    app.edit_cell(3, columns.index("Y"), str(LONG_Y[3]))
    wait()
    check_against(index, LONG_X, LONG_Y, np.repeat(list("ABC"), 6), "1/Yfit²")

    def to_observed(dialog):
        dialog.controls["Weighting"][1].set("1/abs(Y)")

    app.show("result", index)
    drive(to_observed, accept=True)
    app.edit_analysis()
    wait()
    assert app.runs[index].options["Weighting"] == "1/abs(Y)"
    check_against(index, LONG_X, LONG_Y, np.repeat(list("ABC"), 6), "1/abs(Y)")
    assert "Weighting iterations" not in table(index, "Joint fit").index

    # 5. Zero again: the observed run waits with the weighting message; excluding the cell recovers it.
    app.show("data", SHEET)
    app.edit_cell(3, columns.index("Y"), "0")
    wait()
    status = app.status.get()
    assert "need attention" in status and "zero" in status, status
    assert app.runs[index].result is None, "the linked result waits for a valid recalculation"
    app.show("data", SHEET)
    app.current_grid.select((3, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    kept = [i for i in range(18) if i != 3]
    check_against(index, LONG_X[kept], LONG_Y[kept], np.repeat(list("ABC"), 6)[kept], "1/abs(Y)")
    assert joint(index)["N"] == 17
    app.show("result", index)
    shot(root, "window-global-irls-recalculated.png")

    # 6. Series constraints: one fixed intercept per series with 1/Y², on the three series.
    app.show("data", SHEET)
    fixed = {level: value for level, value in INTERCEPTS.items()}

    def constrained(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.controls["Series"][1].set("Series")
        dialog.controls["Model"][1].set("Straight line")
        dialog.parameters.rows["Slope"][0].set("Shared")
        dialog.controls["Weighting"][1].set("1/abs(Yfit)")
        panel = dialog.series_parameters
        dialog.fields.select(panel)
        dialog.refresh_series_tab()
        assert panel.labels == ["A", "B", "C"], panel.labels
        for position, level in enumerate(panel.labels):
            panel.choices.current(position)
            panel.choices.event_generate("<<ComboboxSelected>>")
            panel.rows["Intercept"]["fixed"].set(str(fixed[level]))
        shot(dialog, "window-global-irls-series.png")

    tools.drive_dialog(tools.AnalysisDialog, constrained)
    app.choose_analysis()
    wait()
    pinned = len(app.runs) - 1
    kept_series = np.repeat(list("ABC"), 6)[kept]
    check_against(pinned, LONG_X[kept], LONG_Y[kept], kept_series, "1/abs(Yfit)", fixed=fixed)
    assert (table(pinned, "Parameters")["Scope"] == "Fixed").sum() == 3
    assert bool(joint(pinned)["Weighting converged"])

    # 7. Wide XY: means at each X and individual replicates both follow the closed-form fixed point.
    app.show("data", WIDE)
    replicate_columns = [column for column in WIDE_FRAME.columns if column != "Dose"]
    long_rows = WIDE_FRAME.melt(id_vars="Dose", var_name="Column", value_name="Y")
    long_rows["Series"] = long_rows["Column"].str[0]
    means = long_rows.groupby(["Series", "Dose"], sort=False, as_index=False)["Y"].mean()
    for replicates, source in (("Means at each X", means), ("Individual observations", long_rows)):
        def wide(dialog, replicates=replicates):
            tools.pick_method(dialog, METHOD)
            dialog.controls["Input format"][1].set("Wide XY")
            dialog.update()
            assert placed(dialog, "Y columns") and not placed(dialog, "Y") and not placed(dialog, "Series")
            dialog.controls["X"][1].set("Dose")
            tools.select_columns(dialog, "Y columns", set(replicate_columns))
            dialog.controls["Model"][1].set("Straight line")
            dialog.parameters.rows["Slope"][0].set("Shared")
            dialog.controls["Replicates"][1].set(replicates)
            dialog.controls["Weighting"][1].set("1/abs(Yfit)")

        tools.drive_dialog(tools.AnalysisDialog, wide)
        app.choose_analysis()
        wait()
        position = len(app.runs) - 1
        x_column = "Dose" if "Dose" in source else "X"
        check_against(position, source[x_column], source["Y"], source["Series"], "1/abs(Yfit)")
    app.show("result", position)
    shot(root, "window-global-irls-wide.png")

    # 8. Heavy fit: the interface keeps answering while the worker iterates and profiles.
    app.show("data", MANY)

    def many(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("Conc")
        dialog.controls["Y"][1].set("Rate")
        dialog.controls["Series"][1].set("Enzyme")
        dialog.controls["Model"][1].set("Michaelis–Menten")
        dialog.parameters.rows["Km"][0].set("Shared")
        dialog.controls["Weighting"][1].set("1/Yfit²")
        dialog.controls["Parameter intervals"][1].set("Profile likelihood")

    tools.drive_dialog(tools.AnalysisDialog, many)
    ticks = []
    root.after(20, lambda: ticks.append(time.monotonic()))
    app.choose_analysis()
    assert app.pending is not None, "the calculation must run on the worker"
    started = time.monotonic()
    deadline = started + 120
    while app.pending is not None:
        assert time.monotonic() < deadline, "global fit did not finish"
        root.update()
        ticks.append(time.monotonic())
        time.sleep(.02)
    assert not errors, errors
    assert len(ticks) >= 3, "the interface did not answer during the calculation"
    print(f"global-irls: heavy fit {time.monotonic() - started:.1f} s, {len(ticks)} interface ticks")
    heavy = len(app.runs) - 1
    assert bool(joint(heavy)["Weighting converged"]) and joint(heavy)["Confidence intervals"] == "profile"
    assert table(heavy, "Parameters")["CI 95% low"].notna().all()

    # 9. Save and reopen: the new choices and the confirmed results survive.
    saved = {(r.title, r.slot): (dict(r.options), {k: v.copy() for k, v in r.result.tables.items()})
             for r in app.runs if r.method == METHOD and r.title in {SHEET, WIDE, MANY} and r.result is not None}
    assert len(saved) == 5, len(saved)
    slot = app.runs[index].slot
    app.path = directory / "global-irls-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position in range(len(app.runs)):
        app.open_sheet(("result", position))
        wait()
    reopened = {(r.title, r.slot): r for r in app.runs}
    for key, (options, tables) in saved.items():
        assert reopened[key].options == options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame)

    index = next(i for i, r in enumerate(app.runs) if (r.title, r.slot) == (SHEET, slot))
    assert app.runs[index].options["Weighting"] == "1/abs(Y)"

    # 10. The explanation under Weighting follows the interface language.
    def italian(dialog):
        dialog.controls["Weighting"][1].set("1/Yfit²")
        dialog.update()
        assert "valore stimato" in dialog.weighting_note.cget("text")
        dialog.fields.select(dialog.field_rows["Weighting"][1].master)
        shot(dialog, "window-global-irls-dialog-it.png")

    i18n.set_language("it")
    try:
        app.show("result", index)
        drive(italian, accept=False)
        app.edit_analysis()
        root.update()
    finally:
        i18n.set_language("en")
    for label in fw.FITTED_WEIGHTINGS:
        assert fw.NOTE_KEYS[label] in i18n.CATALOGS["it"] and fw.NOTE_KEYS[label] in i18n.CATALOGS["en"]

    check_recovery(root, app, directory, tools, shot, placed)
    assert not errors, errors


def check_recovery(root, app, directory, tools, shot, placed):
    """An error found by the IRLS on the worker reopens the dialog with the candidate and Weighting focused."""
    errors = tools.errors

    def find(parent):
        for child in parent.winfo_children():
            if isinstance(child, tools.AnalysisDialog):
                return child
            found = find(child)
            if found is not None:
                return found

    def when_open(action, *, accept):
        """Drive the dialog the app reopens by itself once the worker has failed."""
        state = {"done": False}

        def enter(tries=0):
            dialog = find(root)
            if dialog is None:
                if tries > 1200:
                    errors.append("the recovered AnalysisDialog did not open")
                    state["done"] = True
                    return
                root.after(25, lambda: enter(tries + 1))
                return
            try:
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(repr(error))
                dialog.cancel()
            state["done"] = True

        root.after(25, enter)
        return state

    def settle(state, ticks=None):
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            if ticks is not None:
                ticks.append(time.monotonic())
            time.sleep(.02)
        assert not errors, errors

    def candidate_kept(dialog, weighting, message):
        assert dialog.error_label is not None and message in dialog.error_label.cget("text"), dialog.error
        assert dialog.error_label.winfo_manager(), "the error must be visible"
        assert dialog.initial_field == "Weighting"
        assert dialog.fields.select() == str(dialog.field_rows["Weighting"][1].master)
        assert dialog.controls["Weighting"][1].get() == weighting

    def zero_runs():
        return [i for i, r in enumerate(app.runs) if r.title == ZERO]

    # R1. New analysis: the interface keeps processing events while the worker fails, project changes wait,
    #     the dialog returns with the whole candidate, and Unweighted then adds exactly one analysis.
    app.show("data", ZERO)
    before = len(zero_runs())
    project = app.active_project

    def first(dialog):
        tools.pick_method(dialog, METHOD)
        for name in ("X", "Y", "Series"):
            dialog.controls[name][1].set(ZERO_OPTIONS[name])
        dialog.controls["Model"][1].set("Michaelis–Menten")
        dialog.parameters.rows["Km"][0].set("Shared")
        dialog.controls["Weighting"][1].set("1/Yfit²")

    # Hold the worker until a Tk event releases it. Counting polling iterations instead
    # made this check fail on a fast machine even when recovery and responsiveness worked.
    from threading import Event
    release = Event()
    compute = app.compute

    def held_compute(*args, **kwargs):
        assert release.wait(10), "the UI did not release the worker"
        return compute(*args, **kwargs)

    with patch.object(app, "compute", side_effect=held_compute):
        tools.drive_dialog(tools.AnalysisDialog, first)
        app.choose_analysis()
    assert app.pending is not None, "the IRLS must run on the worker"
    assert app.add_project() is None and app.active_project == project, "project changes wait for the worker"
    shots = {}

    def recovered_new(dialog):
        candidate_kept(dialog, "1/Yfit²", "fitted curve is zero")
        assert dialog.method == METHOD and dialog.controls["Model"][1].get() == "Michaelis–Menten"
        assert [dialog.controls[name][1].get() for name in ("X", "Y", "Series")] == ["X", "Y", "Series"]
        assert dialog.parameters.rows["Km"][0].get() == "Shared"
        assert dialog.controls["Input format"][1].get() == "Long table" and placed(dialog, "Y")
        shot(dialog, "window-global-irls-recovered.png")
        shots["new"] = True
        dialog.controls["Weighting"][1].set("Unweighted")

    heartbeat = []

    def release_from_ui():
        heartbeat.append(app.pending is not None and not app.pending.done())
        release.set()

    root.after(0, release_from_ui)
    try:
        settle(when_open(recovered_new, accept=True))
    finally:
        release.set()
    assert shots.get("new") and heartbeat == [True], heartbeat
    assert len(zero_runs()) == before + 1, "one analysis is added after the correction"
    fixed_index = zero_runs()[-1]
    confirmed = app.runs[fixed_index]
    assert confirmed.options["Weighting"] == "Unweighted" and confirmed.options["Shared parameters"] == ["Km"]
    assert confirmed.result.tables["Joint fit"].loc["Weighting", "Value"] == "Unweighted"

    # R2. Editing that analysis to 1/Yfit² fails on the worker; cancelling the restored dialog keeps the
    #     confirmed options, tables, graph, style and layout references.
    tables = {name: table.copy() for name, table in confirmed.result.tables.items()}
    figure, style, options = confirmed.result.figure, confirmed.style, dict(confirmed.options)
    app.layouts.append(Layout("Recovery layout", 1, [confirmed.reference]))
    panels = [list(layout.panels) for layout in app.layouts]

    def to_fitted(dialog):
        dialog.controls["Weighting"][1].set("1/Yfit²")

    def recovered_cancel(dialog):
        candidate_kept(dialog, "1/Yfit²", "fitted curve is zero")
        assert dialog.parameters.rows["Km"][0].get() == "Shared"

    for attempt, (follow, accept) in enumerate(((recovered_cancel, False), (None, True))):
        app.show("result", fixed_index)
        tools.drive_dialog(tools.AnalysisDialog, to_fitted)
        app.edit_analysis()
        assert app.pending is not None
        if follow is None:
            def follow(dialog):
                candidate_kept(dialog, "1/Yfit²", "fitted curve is zero")
                dialog.controls["Weighting"][1].set("1/Y²")
        settle(when_open(follow, accept=accept))
        if attempt == 0:
            assert app.runs[fixed_index] is confirmed and confirmed.options == options
            assert confirmed.result.figure is figure and confirmed.style == style
            for name, table in tables.items():
                pd.testing.assert_frame_equal(confirmed.result.tables[name], table)
            assert [list(layout.panels) for layout in app.layouts] == panels
            assert confirmed.reference in app.layouts[-1].panels
            assert "discarded" in app.status.get(), app.status.get()
    # R3. The corrected edit replaced the confirmed analysis in place.
    assert len(zero_runs()) == before + 1
    assert app.runs[fixed_index].options["Weighting"] == "1/Y²"
    assert app.runs[fixed_index].result.tables["Joint fit"].loc["Weighting", "Value"] == "1/Y²"

    # R4. A missing convergence uses the same recovery (failure injected for this check only).
    app.show("data", SHEET)
    sheet_before = sum(r.title == SHEET for r in app.runs)

    def line(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.controls["Series"][1].set("Series")
        dialog.controls["Model"][1].set("Straight line")
        dialog.parameters.rows["Slope"][0].set("Shared")
        dialog.controls["Weighting"][1].set("1/abs(Yfit)")

    def unconverged(dialog):
        candidate_kept(dialog, "1/abs(Yfit)", "did not converge")
        shot(dialog, "window-global-irls-unconverged.png")
        dialog.controls["Weighting"][1].set("1/abs(Y)")

    with patch.object(fw, "MAX_WEIGHT_REFITS", 1):
        tools.drive_dialog(tools.AnalysisDialog, line)
        app.choose_analysis()
        settle(when_open(unconverged, accept=True))
    assert sum(r.title == SHEET for r in app.runs) == sheet_before + 1
    assert app.runs[-1].options["Weighting"] == "1/abs(Y)" and app.runs[-1].result is not None

    # R5. The independent Nonlinear regression with fitted weights recovers the same way; Cancel adds nothing.
    app.show("data", ZERO)
    count = len(app.runs)

    def independent(dialog):
        tools.pick_method(dialog, "Nonlinear regression")
        dialog.controls["X"][1].set("X")
        tools.select_columns(dialog, "Y columns", {"Y"})
        tools.select_columns(dialog, "Grouping variables", {"Series"})
        dialog.controls["Model"][1].set("Michaelis–Menten")
        dialog.controls["Weighting"][1].set("1/abs(Yfit)")

    def independent_recovered(dialog):
        candidate_kept(dialog, "1/abs(Yfit)", "fitted curve is zero")
        assert dialog.method == "Nonlinear regression"

    tools.drive_dialog(tools.AnalysisDialog, independent)
    app.choose_analysis()
    settle(when_open(independent_recovered, accept=False))
    assert len(app.runs) == count, "a cancelled candidate adds no analysis"

    # R6. Save and reopen after the corrections.
    kept = {(r.title, r.slot): dict(r.options) for r in app.runs if r.title == ZERO}
    app.path = directory / "global-irls-recovery.alab"
    assert app.save()
    app.import_file(app.path)
    for position in range(len(app.runs)):
        app.open_sheet(("result", position))
        tools.wait_for_calculation()
    reopened = {(r.title, r.slot): r for r in app.runs if r.title == ZERO}
    assert {key: dict(r.options) for key, r in reopened.items()} == kept
    assert all(r.result is not None for r in reopened.values())
