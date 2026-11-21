"""Desktop smoke check for the Permutation test for mean difference, driving the real dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_mean_permutation` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=mean-permutation python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/mean_permutation) and generated columns. Exact counts are the
rational enumeration of the fixtures (57 of 126 independent assignments, 16 of 32 sign patterns); Monte Carlo draws
are checked against the documented generator calls. Every widget is driven through its real handler.
"""
import json
import time
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, mean_permutation as mp
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "mean_permutation"
METHOD = mp.METHOD
INDEPENDENT, PAIRED, LARGE, TEXT = "Independent samples", "Paired samples", "Large samples", "Labels"
SHEETS = [mp.RESULTS_SHEET, mp.SETTINGS_SHEET, mp.DRAWS_SHEET]
LARGE_RESAMPLES = 80_000


def large_table(size=300):
    """Two overlapping samples: Exact is far over budget and Monte Carlo runs long enough to be cancelled."""
    generator = np.random.default_rng(2193)
    return pd.DataFrame({"Control": np.round(generator.normal(10, 2, size), 3),
                         "Treated": np.round(generator.normal(10.4, 2, size), 3)})


def rational_counts(first, second):
    """Tail counts of the fixture by exact enumeration with fractions: (two-sided, greater, less, total)."""
    a, b = [Fraction(str(x)) for x in first], [Fraction(str(x)) for x in second]
    pool = a + b
    observed = sum(a) / len(a) - sum(b) / len(b)
    null = []
    for chosen in combinations(range(len(pool)), len(a)):
        inside = set(chosen)
        x = [pool[i] for i in chosen]
        y = [pool[i] for i in range(len(pool)) if i not in inside]
        null.append(sum(x) / len(x) - sum(y) / len(y))
    return (sum(abs(v) >= abs(observed) for v in null), sum(v >= observed for v in null),
            sum(v <= observed for v in null), len(null))


def paired_draws(differences, resamples, seed):
    generator = np.random.Generator(np.random.PCG64(seed))
    return np.array([np.where(generator.integers(0, 2, size=len(differences), dtype="int64") == 1,
                              differences, -differences).mean() for _ in range(resamples)])


def check_mean_permutation(root, app, directory, tools):
    """Exercise both locales using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check(root, app, directory, tools):  # noqa: C901 - one linear scenario, step by step
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "mean-permutation"
    out.mkdir(exist_ok=True)
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    independent = pd.read_csv(DATA / "independent.csv")
    paired = pd.read_csv(DATA / "paired.csv")
    labels = independent.assign(Label=list("abcde"))
    path = directory / "mean-permutation.alab"
    save_project(path, {INDEPENDENT: Dataset(independent.copy()), PAIRED: Dataset(paired.copy()),
                        LARGE: Dataset(large_table()), TEXT: Dataset(labels)})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "theme": "modern" if app.modern_workspace else "standard",
              "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def pick(dialog, field, value):
        binding = dialog.choice_bindings[field]
        binding.display.set(binding.labels[binding.values.index(value)])
        dialog.update()

    def shown(dialog, field):
        return bool(dialog.field_rows[field][1].winfo_manager())

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert (caption or field).lower() in message.lower() and contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), field
        assert dialog.initial_focus is dialog.field_rows[field][1], "the field to correct must hold the focus"
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

    def button(dialog, text):
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button) and child.cget("text") == text:
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(dialog)

    def reachable(dialog):
        """Run Analysis, Cancel and every tab lie inside the screen at the current size."""
        dialog.update()
        for text in (i18n.ui("Run Analysis"), i18n.ui("Cancel")):
            found = button(dialog, text)
            assert found is not None and found.winfo_viewable(), text
            assert found.winfo_rooty() + found.winfo_height() <= screen[1], (text, found.winfo_rooty(), screen)
            assert found.winfo_rootx() + found.winfo_width() <= screen[0], text
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
        dialog.fields.select(0)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def values(index):
        return table(index, mp.RESULTS_SHEET).iloc[0]

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    def gids(index):
        axes = app.runs[index].result.figure.axes[0]
        return {artist.get_gid() for artist in [*axes.patches, *axes.lines, *axes.texts] if artist.get_gid()}

    def wait_long(seconds=120):
        deadline = time.monotonic() + seconds
        while app.pending is not None:
            assert time.monotonic() < deadline, "the calculation did not finish"
            root.update()
            time.sleep(.02)
        assert not errors, errors

    # 1. English dialog on the independent fixture: the same column refused on Second, a seed that is not a number
    # and one beyond 64 bits refused on Seed, then Exact hides Resamples and Seed and keeps the valid seed.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Data", "Test"]
        assert [controls[name][1].get() for name in ("Design", "Alternative", "Method")] == [
            "Independent", "Two-sided", "Auto"]
        assert "126 assignments" in dialog.permutation_notes["method"].cget("text")
        controls["First"][1].set("First")
        controls["Second"][1].set("First")
        rejected(dialog, "Second", "different from First", "window-mean-permutation-error.png")
        controls["Second"][1].set("Second")
        pick(dialog, "Method", "Monte Carlo")
        assert shown(dialog, "Seed") and shown(dialog, "Resamples")
        controls["Seed"][1].set("seven")
        rejected(dialog, "Seed", "whole number")
        controls["Seed"][1].set(str(2**64))
        rejected(dialog, "Seed", "18446744073709551615", "window-mean-permutation-seed-error.png")
        controls["Seed"][1].set(str(2**64 - 1))
        pick(dialog, "Method", "Exact")
        assert not shown(dialog, "Seed") and not shown(dialog, "Resamples")
        assert dialog.permutation_notes["method"].cget("text") == (
            "Exact enumerates all 126 assignments; Resamples and Seed are ignored.")
        controls["Keep draws"][1].set(True)
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-mean-permutation-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-mean-permutation-test" + suffix + ".png")
        dialog.fields.select(0)

    main = analyse_with(english, INDEPENDENT)
    options = app.runs[main].options
    assert options == {"First": "First", "Second": "Second", "Design": "Independent", "Alternative": "Two-sided",
                       "Method": "Exact", "Resamples": 9999, "Seed": 2**64 - 1, "Keep draws": True,
                       "Show graph": True}, options
    assert list(app.runs[main].result.tables) == SHEETS, list(app.runs[main].result.tables)
    two, greater, less, total = rational_counts(independent["First"].dropna(), independent["Second"])
    row = values(main)
    assert (int(row["Tail count"]), int(row["Draws"]), row["Mode used"]) == (two, total, "Exact"), row
    assert (two, greater, less, total) == (57, 30, 104, 126)
    assert abs(float(row["p"]) - two / total) < 1e-15 and abs(float(row["Mean difference"]) - 1.75) < 1e-12
    assert list(table(main, mp.DRAWS_SHEET)["Draw"]) == list(range(1, 127))
    done("english dialog: same column on Second, two seeds refused on Seed; Exact 57/126 as the rational count")

    app.show("result", main)
    root.update()
    shot(root, "window-mean-permutation-results" + suffix + ".png")
    app.show("graph", main)
    root.update()
    axes = app.runs[main].result.figure.axes[0]
    assert {mp.OBSERVED_GID, mp.MIRROR_GID, mp.SUMMARY_GID} <= gids(main), gids(main)
    observed = next(line for line in axes.lines if line.get_gid() == mp.OBSERVED_GID)
    assert list(observed.get_xdata()) == [1.75, 1.75]
    assert not getattr(axes, "_tramastat_non_native", False)
    assert sum(patch.get_height() for patch in axes.patches) == 126
    shot(root, "window-mean-permutation-graph" + suffix + ".png")
    done("native histogram: 126 assignments, observed line at 1.75 and its two-sided mirror")

    # 2. Monte Carlo on the paired fixture with a 64-bit seed: the draws are the documented generator calls.
    def monte_carlo(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        controls["First"][1].set("First")
        controls["Second"][1].set("Second")
        pick(dialog, "Design", "Paired")
        assert "Paired samples" in dialog.permutation_notes["design"].cget("text")
        pick(dialog, "Alternative", "Greater")
        pick(dialog, "Method", "Monte Carlo")
        controls["Resamples"][1].set("199")
        controls["Seed"][1].set(str(2**64 - 1))
        controls["Keep draws"][1].set(True)

    paired_index = analyse_with(monte_carlo, PAIRED)
    complete = paired.dropna()
    differences = (complete["First"] - complete["Second"]).to_numpy()
    expected = paired_draws(differences, 199, 2**64 - 1)
    draws = table(paired_index, mp.DRAWS_SHEET)
    np.testing.assert_allclose(draws["Statistic"].to_numpy(float), expected, rtol=0, atol=1e-12)
    count = int(np.sum(expected >= differences.mean() - 1e-9))
    row = values(paired_index)
    assert (int(row["N first"]), int(row["N second"]), int(row["Draws"])) == (5, 5, 199), row
    assert int(row["Tail count"]) == count and float(row["p"]) == (count + 1) / 200, row
    settings = table(paired_index, mp.SETTINGS_SHEET)["Value"]
    assert settings["Seed"] == "18446744073709551615" and settings["Incomplete or excluded pairs omitted"] == 2
    longer = analyse(METHOD, app.tables[PAIRED].frame(mask_excluded=True),
                     {**app.runs[paired_index].options, "Resamples": 400})
    pd.testing.assert_frame_equal(longer.tables[mp.DRAWS_SHEET].iloc[:199], draws)
    done("paired Monte Carlo: 199 draws equal integers(0, 2) per resample; 400 resamples keep the prefix")

    # 3. Exact over budget is refused on Method; Auto simulates, Cancel keeps the last result and a cancelled new
    # analysis adds nothing.
    def large(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        controls["First"][1].set("Control")
        controls["Second"][1].set("Treated")
        pick(dialog, "Method", "Exact")
        rejected(dialog, "Method", "200,000 assignments", "window-mean-permutation-method-error.png")
        pick(dialog, "Method", "Auto")
        assert "simulates" in dialog.permutation_notes["method"].cget("text")
        controls["Resamples"][1].set(str(100_000))
        rejected(dialog, "Resamples", "Use 83,333 resamples or fewer.")
        controls["Resamples"][1].set(str(LARGE_RESAMPLES))
        controls["Seed"][1].set("93")

    started = time.perf_counter()
    app.show("data", LARGE)
    tools.drive_dialog(tools.AnalysisDialog, large)
    app.choose_analysis()
    wait_long()
    large_index = len(app.runs) - 1
    report["large_seconds"] = round(time.perf_counter() - started, 3)
    assert app.runs[large_index].method == METHOD
    row = values(large_index)
    assert (row["Mode used"], int(row["Draws"])) == ("Monte Carlo", LARGE_RESAMPLES), row
    previous = app.runs[large_index].result
    app.show("result", large_index)
    app.recalculate(large_index)
    assert app.calculation is not None, "the permutation test offers Cancel"
    time.sleep(.3)
    clicked = time.perf_counter()
    app.calculation.cancel.set()
    wait_long()
    report["cancel_latency_seconds"] = round(time.perf_counter() - clicked, 3)
    assert app.runs[large_index].result is previous, "Cancel keeps the last completed result"
    assert app.status.get() == f"{METHOD} cancelled. The last completed results are kept.", app.status.get()
    count = len(app.runs)
    app.show("data", LARGE)
    tools.drive_dialog(tools.AnalysisDialog, lambda dialog: (tools.pick_method(dialog, METHOD),
                                                             dialog.controls["First"][1].set("Control"),
                                                             dialog.controls["Second"][1].set("Treated"),
                                                             dialog.controls["Resamples"][1].set("80000")))
    app.choose_analysis()
    assert app.calculation is not None
    app.calculation.cancel.set()
    wait_long()
    assert len(app.runs) == count, "a cancelled new analysis adds no recipe"
    assert app.status.get() == f"{METHOD} cancelled. No analysis was added.", app.status.get()
    done(f"Exact refused on Method, Resamples capped at 83,333; {LARGE_RESAMPLES:,} draws in "
         f"{report['large_seconds']} s; Cancel in {report['cancel_latency_seconds']} s keeps the result")

    # 4. Italian dialog on the paired fixture: captions, choices and messages; the recipe stays canonical.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
        assert captions["First"] == "Primo campione" and captions["Keep draws"] == "Salva distribuzione nulla"
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Dati", "Test"]
        assert list(dialog.field_rows["Alternative"][1].cget("values")) == [
            "Bilaterale", "Maggiore (Primo > Secondo)", "Minore (Primo < Secondo)"]
        dialog.controls["First"][1].set("First")
        dialog.controls["Second"][1].set("Second")
        dialog.field_rows["Design"][1].set("Appaiati")
        dialog.field_rows["Design"][1].event_generate("<<ComboboxSelected>>")
        dialog.update()
        assert dialog.controls["Design"][1].get() == "Paired"
        assert dialog.permutation_notes["design"].cget("text").startswith("Campioni appaiati")
        pick(dialog, "Method", "Monte Carlo")
        dialog.controls["Seed"][1].set("-3")
        rejected(dialog, "Seed", "da 0 a 18446744073709551615", "window-mean-permutation-it-error.png",
                 caption="Seme")
        dialog.controls["Seed"][1].set("0")
        pick(dialog, "Method", "Auto")
        assert dialog.permutation_notes["method"].cget("text") == (
            "Con queste colonne Automatico enumera esattamente tutte le 32 assegnazioni: Repliche e Seme non sono "
            "usati.")
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-mean-permutation-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-mean-permutation-it-test" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, PAIRED)
        recipe = app.runs[italian_index].options
        assert (recipe["Design"], recipe["Method"], recipe["Alternative"], recipe["Seed"]) == (
            "Paired", "Auto", "Two-sided", 0), recipe
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-mean-permutation-it-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    row = values(italian_index)
    assert (int(row["Tail count"]), int(row["Draws"]), row["Mode used"]) == (16, 32, "Exact"), row
    done("italian dialog: captions, choices, Seme refused in Italian; paired Auto exact 16/32, canonical recipe")

    # 5. Edit a value and exclude a cell: the result follows the worksheet. Blanking First down to one value then
    # reopens the dialog on First with the last result kept and flagged, and restoring the values recovers.
    app.show("data", INDEPENDENT)
    first_column = app.tables[INDEPENDENT].raw.columns.get_loc("First")
    second_column = app.tables[INDEPENDENT].raw.columns.get_loc("Second")
    app.edit_cell(0, first_column, "2")
    wait()
    frame = app.tables[INDEPENDENT].frame(mask_excluded=True)
    direct = analyse(METHOD, frame, dict(app.runs[main].options))
    pd.testing.assert_frame_equal(table(main, mp.RESULTS_SHEET), direct.tables[mp.RESULTS_SHEET])
    assert abs(float(values(main)["Mean difference"]) - 2.0) < 1e-12
    app.show("data", INDEPENDENT)
    app.current_grid.select((0, second_column))
    app.toggle_exclusion()
    wait()
    row = values(main)
    assert (int(row["N first"]), int(row["N second"]), int(row["Draws"])) == (4, 4, 70), row
    assert table(main, mp.SETTINGS_SHEET)["Value"]["Missing or excluded cells, Second"] == 1
    done("an edited value and an excluded cell recalculate: 4 + 4 values, 70 assignments")

    for position in (3, 2):
        app.show("data", INDEPENDENT)
        app.edit_cell(position, first_column, "")
        wait()
    assert (int(values(main)["N first"]), int(values(main)["Draws"])) == (2, 15), values(main)
    kept_tables = {name: frame.copy() for name, frame in app.runs[main].result.tables.items()}
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
            banner = dialog.error_label.cget("text") if dialog.error_label is not None else ""
            assert "First: at least 2 values are needed; 1 found." in banner, banner
            assert dialog.initial_field == "First"
            assert dialog.fields.select() == page_of(dialog, "First")
            assert dialog.controls["Method"][1].get() == "Exact"
            shot(dialog, "window-mean-permutation-recovered" + suffix + ".png")
            dialog.cancel()
        except Exception as error:  # noqa: BLE001 - reported through the smoke error list
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    app.show("data", INDEPENDENT)
    root.after(25, recovered)
    app.edit_cell(1, first_column, "")
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    assert not errors, errors
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[main].result.tables[name], frame)
    assert app.runs[main].calculation_error and "1 found" in app.runs[main].calculation_error
    app.show("result", main)
    assert app.stale_calculation_note() is not None, "the kept result must be flagged"
    app.show("data", INDEPENDENT)
    for position, value in ((1, "3"), (2, "4"), (3, "7")):
        app.show("data", INDEPENDENT)
        app.edit_cell(position, first_column, value)
        wait()
    assert (int(values(main)["N first"]), int(values(main)["Draws"])) == (4, 70), values(main)
    assert app.runs[main].calculation_error is None and app.stale_calculation_note(("result", main)) is None
    done("one value left in First keeps the last result flagged, reopens the dialog on First; restoring recovers")

    # 6. Format Graph and the Inspector restyle the figure without drawing a new null sample.
    computed = []
    original_compute = app.compute

    def counting(*args, **kwargs):
        computed.append(args[0].method if args else None)
        return original_compute(*args, **kwargs)

    app.compute = counting
    try:
        result = app.runs[main].result
        draws_before = table(main, mp.DRAWS_SHEET).copy()
        app.show("graph", main)
        root.update()
        app.toggle_inspector()
        root.update()
        panel = app.inspector
        assert panel is not None and panel.elements, "the Inspector must offer the drawn elements"
        report["inspector"] = [element["name"] for element in panel.elements]
        element = next((item for item in panel.elements if mp.OBSERVED_LABEL in item["name"]), panel.elements[0])
        panel.select_group(element["key"])
        panel.vars["element:color"].set("#9b4174")
        widget = panel.fields["color"]["widget"]
        widget.focus_force()
        root.update()
        widget.event_generate("<Return>")
        root.update()
        assert panel.apply(), panel.errors
        assert "#9b4174" in str(app.runs[main].style), app.runs[main].style
        confirmed = app.runs[main].style
        panel.vars["element:color"].set("#117733")
        widget.event_generate("<Return>")
        root.update()
        assert panel.has_draft
        panel.cancel()
        root.update()
        assert app.inspector is None and app.runs[main].style == confirmed, "Cancel restores the confirmed style"
        title = "Null $distribution$ of mean_diff"
        tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set(title))
        app.format_graph()
        wait()
        axes = app.runs[main].result.figure.axes[0]
        assert axes.get_title() == title and not axes.title.get_parse_math()
        assert {mp.OBSERVED_GID, mp.SUMMARY_GID} <= gids(main), "styling keeps the observed line and the summary"
        assert app.runs[main].result is result and not computed, computed
        pd.testing.assert_frame_equal(table(main, mp.DRAWS_SHEET), draws_before)
    finally:
        app.compute = original_compute
    app.show("graph", main)
    root.update()
    shot(root, "window-mean-permutation-styled" + suffix + ".png")
    done("Inspector Apply and Cancel, Format Graph with a literal $ title; no new null sample")

    # 7. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure and a two-panel layout.
    app.show("result", main)
    columns = {mp.RESULTS_SHEET: mp.RESULT_COLUMNS, mp.SETTINGS_SHEET: ["Value"], mp.DRAWS_SHEET: mp.DRAW_COLUMNS}
    for position, name in enumerate(app.runs[main].result.tables):
        app.result_tabs.select(position)
        target = out / f"mean-permutation-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        assert list(exported.columns) == [c for c in columns[name] if c != exported.index.name], (
            name, list(exported.columns))
    app.show("graph", main)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"mean-permutation.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "mean-permutation.svg").read_text(encoding="utf-8")
    assert f'id="{mp.OBSERVED_GID}' in svg and f'id="{mp.BIN_GID}-1' in svg, "stable ids in the SVG"
    assert "<image" not in svg and "#9b4174" in svg.lower(), "bars and lines stay vector in the styled colour"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "mean-permutation.pdf")
    assert "Observed" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("Permutation panels", 2,
                              [app.runs[main].reference, app.runs[paired_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    target = exports / "layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    [(_, layout_text, layout_images)] = read_pdf(target)
    assert layout_images == 0, "the two-panel layout stays vector"
    layout_svg = exports / "layout.svg"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    layout_text = layout_svg.read_text(encoding="utf-8")
    assert "<svg" in layout_text[:600] and "<image" not in layout_text
    shot(root, "window-mean-permutation-layout" + suffix + ".png")
    done("CSV of each sheet, PNG, SVG, PDF and a two-panel layout kept vector")

    # 8. Save, reopen with the graph first: canonical recipes with the 64-bit seed and the same tables.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method == METHOD}
    assert len(expected_runs) >= 4, sorted(expected_runs)
    app.path = directory / "mean-permutation-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD:
            app.open_sheet(("graph", position))
            wait_long()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame)
    key = next(k for k in expected_runs if k[0] == PAIRED and expected_runs[k][0]["Method"] == "Monte Carlo")
    assert reopened[key].options["Seed"] == 2**64 - 1 and type(reopened[key].options["Seed"]) is int
    key = next(k for k in expected_runs if k[0] == INDEPENDENT)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    app.show("graph", position)
    root.update()
    assert app.runs[position].result.figure.axes[0].get_title() == title
    assert {mp.OBSERVED_GID, mp.SUMMARY_GID} <= gids(position)
    shot(root, "window-mean-permutation-reopened" + suffix + ".png")
    done("save and reopen from the graph: recipes, 64-bit seed, tables and style unchanged")

    # 9. Use Result as Data keeps the null distribution in evaluation order.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(2)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns) == mp.DRAW_COLUMNS and len(frame) == 70, (list(frame.columns), len(frame))
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data on the null distribution")

    # The same text column refused when chosen in a new dialog keeps the dialog open on Second.
    def text_column(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["First"][1].set("First")
        dialog.controls["Second"][1].set("Label")
        rejected(dialog, "Second", "source row 1 is not a number (a)")
        dialog.controls["Second"][1].set("Second")

    analyse_with(text_column, TEXT)
    done("a text column is refused on Second in the dialog")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    assert not errors, errors
