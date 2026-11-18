"""Desktop smoke check for Repeated-measures correlation, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_rmcorr` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=rmcorr python tramastat.py --smoke DIR``. With the Modern theme, point
``XDG_CONFIG_HOME`` (``APPDATA`` on Windows) at a folder whose ``tramastat/preferences.json`` holds
``{"theme": "modern"}``; the screenshots then carry ``-modern``.

Synthetic data only: the packaged fixtures (tests/data/rmcorr). The expected numbers are the frozen values of
expected.json, never computed by the module under test, except where a step recalculates the same recipe through the
dispatcher to prove that the dialog, the worker and the saved recipe agree.
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, rmcorr, ui_theme
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "rmcorr"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = rmcorr.RMCORR
REPEATED, ANOTHER, LEGACY = "Repeated", "Another subject", "Legacy Pearson"
SEED, REPLICATES = "867531", "200"
SHEETS = [rmcorr.SUMMARY, rmcorr.PARTICIPANTS, rmcorr.PAIRS, rmcorr.BOOTSTRAP]


def check_rmcorr(root, app, directory, tools):
    """Exercise both locales and both window sizes using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_rmcorr(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_rmcorr(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    large = screen[0] >= 1600 and screen[1] >= 1000
    theme = "-modern" if ui_theme.is_modern() else ""
    out = directory / ("rmcorr" + theme)
    out.mkdir(exist_ok=True)
    repeated = pd.read_csv(DATA / "repeated.csv")
    another = pd.read_csv(DATA / "another-subject.csv", dtype={"Participant": str})
    legacy = repeated.dropna().reset_index(drop=True)
    path = directory / f"rmcorr{theme}.alab"
    save_project(path, {REPEATED: Dataset(repeated.copy()), ANOTHER: Dataset(another.copy()),
                        LEGACY: Dataset(legacy.copy())})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "theme": "modern" if theme else "standard", "checks": []}

    def done(name):
        report["checks"].append(name)

    def size(geometry):
        root.geometry(geometry + "+0+0")
        root.update()
        return "-" + geometry

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), field
        target = dialog.initial_focus
        assert target is not None and target.winfo_exists(), "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
        if shot_name:
            shot(dialog, shot_name)
        return message

    def states(dialog):
        return {str(dialog.field_rows[name][1].cget("state")) for name in rmcorr.BOOTSTRAP_FIELDS}

    def notes(dialog):
        wanted = (i18n.tr("rmcorr.note.model"), i18n.tr("rmcorr.note.bootstrap"))
        return [child for tab in dialog.fields.tabs() for child in dialog.nametowidget(tab).winfo_children()
                if child.winfo_class() == "TLabel" and child.cget("text") in wanted]

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
        """Run Analysis, every tab and both notes lie inside the screen at the current size."""
        dialog.update()
        button = run_button(dialog)
        assert button is not None and button.winfo_viewable()
        assert button.winfo_rooty() + button.winfo_height() <= screen[1], (button.winfo_rooty(), screen)
        assert button.winfo_rootx() + button.winfo_width() <= screen[0]
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
            for label in notes(dialog):
                if label.winfo_viewable():
                    assert label.winfo_reqwidth() <= dialog.fields.winfo_width(), "the note must wrap"
        dialog.fields.select(0)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def gids(index):
        axes = app.runs[index].result.figure.axes[0]
        return {str(artist.get_gid()) for artist in [*axes.lines, *axes.collections]
                if str(artist.get_gid()).startswith("rmcorr-")}

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    # 1. English dialog at 1024x768: Subject used as X refused on X, corrected in the same dialog; the bootstrap fields
    # follow the interval; the frozen bootstrap recipe.
    suffix = size("1024x768") + theme

    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == ["Variables", "Options"]
        assert [dialog.field_rows[name][0].cget("text") for name in controls] == [
            "Subject", "X", "Y", "Confidence interval", "Confidence level (%)", "Bootstrap replicates", "Seed",
            "Show graph"]
        assert len(notes(dialog)) == 2 and "Pearson" in notes(dialog)[0].cget("text")
        assert states(dialog) == {"disabled"}, "without the bootstrap its fields are inactive"
        controls["Subject"][1].set("Participant")
        controls["X"][1].set("Participant")
        controls["Y"][1].set("Signal")
        rejected(dialog, "X", "three different columns", "window-rmcorr-error" + suffix + ".png")
        controls["X"][1].set("Day")
        controls["Confidence interval"][1].set("Subject bootstrap")
        assert states(dialog) == {"normal"}
        controls["Bootstrap replicates"][1].set("99")
        rejected(dialog, "Bootstrap replicates", "100")
        controls["Bootstrap replicates"][1].set(REPLICATES)
        controls["Seed"][1].set(SEED)
        reachable(dialog)
        shot(dialog, "window-rmcorr-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-rmcorr-options" + suffix + ".png")
        dialog.fields.select(0)

    main = analyse_with(english, REPEATED)
    options = app.runs[main].options
    assert options == {"Subject": "Participant", "X": "Day", "Y": "Signal", "Confidence interval": "Subject bootstrap",
                       "Confidence level (%)": 95.0, "Bootstrap replicates": 200, "Seed": 867531,
                       "Show graph": True}, options
    assert list(app.runs[main].result.tables) == SHEETS, list(app.runs[main].result.tables)
    row = table(main, rmcorr.SUMMARY).iloc[0]
    for name in ("N", "Subjects", "df"):
        assert int(row[name]) == EXPECTED[name], (name, row[name])
    for name in ("Coefficient", "Slope", "t", "p"):
        np.testing.assert_allclose(float(row[name]), EXPECTED[name], rtol=1e-12, err_msg=name)
    np.testing.assert_allclose([float(row["Lower"]), float(row["Upper"])], EXPECTED["Interval"], rtol=1e-12)
    assert int(row["Bootstrap valid"]) == EXPECTED["Bootstrap valid"] and row["Seed"] == SEED, row
    replicates = table(main, rmcorr.BOOTSTRAP)
    np.testing.assert_allclose(replicates["Coefficient"].to_numpy(float)[:5], EXPECTED["Bootstrap first five"],
                               rtol=1e-12)
    participants = table(main, rmcorr.PARTICIPANTS)
    assert participants["Subject"].tolist() == ["A", "B", "C", "D"], participants
    assert participants["Status"].tolist() == ["Used", "Used", "Used", "Singleton"], participants
    pairs = table(main, rmcorr.PAIRS)
    assert pairs["Source row"].tolist() == list(range(1, len(repeated) + 1)), pairs["Source row"].tolist()
    assert (pairs["Status"] == "Missing pair").sum() == 1
    done("english dialog: Subject as X refused on X, 99 replicates refused, frozen r, p, interval and replicates")

    app.show("result", main)
    app.result_tabs.select(0)
    shot(root, "window-rmcorr-results" + suffix + ".png")
    app.show("graph", main)
    root.update()
    figure = app.runs[main].result.figure
    axes = figure.axes[0]
    assert {f"rmcorr-fit-{n}" for n in range(1, 4)} <= gids(main), gids(main)
    legend = [text.get_text() for text in axes.get_legend().get_texts()]
    assert legend[:3] == ["A", "B", "C"], legend
    assert not any(text.get_parse_math() for text in axes.get_legend().get_texts())
    assert getattr(axes, "_tramastat_numeric_axes", None) == ("x", "y")
    shot(root, "window-rmcorr-graph" + suffix + ".png")
    done("graph: one fit per used subject with stable ids, literal legend")

    # 2. Format Graph changes the title without recalculating.
    calls = []
    original = rmcorr.calculate

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    bootstrap_before = table(main, rmcorr.BOOTSTRAP).copy()
    with patch.object(rmcorr, "calculate", counted):
        tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Within $subject$ _r_"))
        app.format_graph()
        wait()
    assert calls == [], "a style change must not resample"
    assert app.runs[main].result.figure.axes[0].get_title() == "Within $subject$ _r_"
    pd.testing.assert_frame_equal(table(main, rmcorr.BOOTSTRAP), bootstrap_before)
    app.show("graph", main)
    root.update()
    shot(root, "window-rmcorr-formatted" + suffix + ".png")
    done("Format Graph with literal text and no recalculation")

    # 3. Italian dialog at 1600x1000 on another worksheet: Y equal to X refused with the Italian banner.
    suffix = (size("1600x1000") if large else size("1024x768") + "-only") + theme
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
        assert captions[:4] == ["Soggetto", "X", "Y", "Intervallo di confidenza"], captions
        assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == ["Variabili", "Opzioni"]
        assert list(dialog.field_rows["Confidence interval"][1].cget("values")) == ["Nessuno", "Bootstrap per soggetti"]
        assert notes(dialog)[0].cget("text") == i18n.tr("rmcorr.note.model")
        dialog.controls["Subject"][1].set("Participant")
        dialog.controls["X"][1].set("Day")
        dialog.controls["Y"][1].set("Day")
        rejected(dialog, "Y", "tre colonne diverse", "window-rmcorr-it-error" + suffix + ".png", caption="Y")
        dialog.controls["Y"][1].set("Signal")
        reachable(dialog)
        shot(dialog, "window-rmcorr-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-rmcorr-it-options" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        second = analyse_with(italian, ANOTHER)
        assert app.runs[second].options["Confidence interval"] == "None", "the recipe keeps the canonical token"
        assert list(app.runs[second].result.tables) == SHEETS[:3]
        labels = table(second, rmcorr.PARTICIPANTS)["Subject"].tolist()
        assert labels[0] == "001", labels
        app.show("result", second)
        app.result_tabs.select(0)
        shot(root, "window-rmcorr-it-results" + suffix + ".png")
        app.show("graph", second)
        root.update()
        texts = [text.get_text() for text in app.runs[second].result.figure.axes[0].get_legend().get_texts()]
        assert texts[0] == "001", texts
        shot(root, "window-rmcorr-it-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    done("italian dialog: Y equal to X refused with the Italian banner, literal subject labels")

    # 4. Edit a value and exclude a cell: the worker recalculates the same recipe and seed.
    app.show("data", REPEATED)
    signal = app.tables[REPEATED].raw.columns.get_loc("Signal")
    day = app.tables[REPEATED].raw.columns.get_loc("Day")
    before = table(main, rmcorr.SUMMARY).copy()
    app.edit_cell(1, signal, "13")
    wait()
    changed = table(main, rmcorr.SUMMARY)
    assert not changed.equals(before), "a value edit recalculates"
    want = analyse(METHOD, app.tables[REPEATED].frame(mask_excluded=True), dict(app.runs[main].options))
    for name in SHEETS:
        pd.testing.assert_frame_equal(table(main, name), want.tables[name])
    app.show("data", REPEATED)
    app.current_grid.select((2, day))
    app.toggle_exclusion()
    wait()
    assert int(table(main, rmcorr.SUMMARY).iloc[0]["N"]) == EXPECTED["N"] - 1
    assert table(main, rmcorr.PAIRS).iloc[2]["Status"] == "Missing pair"
    done("value edit and excluded cell recalculate with the same seed")

    # 5. A value without a subject: the confirmed result is kept and the dialog reopens on Subject.
    app.show("result", main)
    kept_tables = {name: frame.copy() for name, frame in app.runs[main].result.tables.items()}
    kept_options = dict(app.runs[main].options)
    state = {"done": False}

    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(root)

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
            assert "no subject" in banner and banner.startswith("Subject"), banner
            assert dialog.initial_field == "Subject"
            assert dialog.fields.select() == page_of(dialog, "Subject")
            assert dialog.controls["Seed"][1].get() == SEED
            shot(dialog, "window-rmcorr-recovered" + suffix + ".png")
            dialog.cancel()
        except Exception as error:
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    subject = app.tables[REPEATED].raw.columns.get_loc("Participant")
    app.show("data", REPEATED)
    root.after(25, recovered)
    app.edit_cell(0, subject, "")
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    assert not errors, errors
    assert app.runs[main].options == kept_options
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[main].result.tables[name], frame)
    assert app.runs[main].calculation_error and "no subject" in app.runs[main].calculation_error
    app.show("result", main)
    assert app.stale_calculation_note() is not None, "the stale result must be flagged"
    app.show("data", REPEATED)
    app.edit_cell(0, subject, "A")
    wait()
    assert app.runs[main].calculation_error is None and app.stale_calculation_note(("result", main)) is None
    done("a value without subject keeps the result, reopens Subject and recovers")

    # 6. Cancel a long bootstrap: the last completed result is kept, then a restart gives the same replicates.
    rng = np.random.default_rng(7)
    subjects = np.repeat(np.arange(200), 5)
    x = rng.normal(size=len(subjects))
    big = pd.DataFrame({"Participant": subjects, "Day": x, "Signal": x + rng.normal(size=len(subjects))})
    app._add_tables({"Big": big})
    long_run = tools.Run(METHOD, "Big", {**kept_options, "Bootstrap replicates": 10_000})
    app.add_result(long_run, app.compute(long_run, big))
    long_index = app.runs.index(long_run)
    previous = long_run.result
    app.show("result", long_index)
    app.recalculate(long_index)
    assert app.calculation is not None, "a bootstrap run offers Cancel"
    app.calculation.cancel.set()
    wait()
    assert app.runs[long_index].result is previous, "Cancel keeps the last completed result"
    assert app.status.get() == f"{METHOD} cancelled. The last completed results are kept.", app.status.get()
    app.recalculate(long_index)
    wait()
    assert app.runs[long_index].result is not previous and not errors, errors
    pd.testing.assert_frame_equal(app.runs[long_index].result.tables[rmcorr.BOOTSTRAP], previous.tables[rmcorr.BOOTSTRAP])
    done("Cancel during 10,000 replicates and a restart with identical replicates")

    # 7. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure.
    app.show("result", main)
    for position, name in enumerate(SHEETS):
        app.result_tabs.select(position)
        target = out / f"rmcorr-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
    assert list(pd.read_csv(out / "rmcorr-2.csv", index_col=0, encoding="utf-8-sig").columns) == rmcorr.PAIR_COLUMNS
    app.show("graph", main)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"rmcorr.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "rmcorr.svg").read_text(encoding="utf-8")
    assert 'id="rmcorr-fit-1"' in svg and "<image" not in svg, "the fits stay named vector paths"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "rmcorr.pdf")
    assert "Within" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    done("CSV of four sheets, PNG, SVG with stable ids and PDF without images")

    # A Pearson recipe written before this method existed keeps its table.
    pearson = tools.Run("Correlation", LEGACY, {"X": "Day", "Y": "Signal", "Method": "Pearson"})
    app.add_result(pearson, app.compute(pearson, legacy))
    pearson_before = {name: frame.copy() for name, frame in pearson.result.tables.items()}

    # 8. Save and reopen from the graph: canonical recipes, the same tables, the same Pearson result.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method in (METHOD, "Correlation")
                     and run.title != "Big"}
    assert len(expected_runs) >= 3, sorted(expected_runs)
    app.path = directory / f"rmcorr-saved{theme}.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD and run.title != "Big":
            app.open_sheet(("graph", position) if run.options.get("Show graph", True) else ("result", position))
            wait()
        elif run.method == "Correlation":
            app.open_sheet(("result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-12)
    for name, frame in pearson_before.items():
        pd.testing.assert_frame_equal(reopened[(LEGACY, pearson.slot)].result.tables[name], frame, rtol=1e-12)
    key = next(k for k in expected_runs if k[0] == REPEATED)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert reopened[key].options["Seed"] == 867531 and isinstance(reopened[key].options["Seed"], int)
    app.show("graph", position)
    root.update()
    assert {f"rmcorr-fit-{n}" for n in range(1, 4)} <= gids(position)
    shot(root, "window-rmcorr-reopened" + suffix + ".png")
    done("save and reopen from the graph; the Pearson recipe is unchanged")

    # 9. Use Result as Data keeps the pairs sheet with its source rows.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(SHEETS.index(rmcorr.PAIRS))
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns) == rmcorr.PAIR_COLUMNS and len(frame) == len(repeated), frame.columns
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data on Pairs")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
