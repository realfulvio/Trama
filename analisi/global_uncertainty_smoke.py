"""Desktop smoke for Global fit custom equation 0.70: response bands and predictions for new X.

Drives the real Analyze dialog, Format Graph, the Inspector, the worksheet, Use Result as Data, the
exports and a two-panel layout in the real window. Expected numbers are the independent oracles of
tests/data/global_uncertainty/expected.json (exact rational algebra and an analytic-Jacobian fit), not
the engine under test.

Linux/Xvfb only, with the widgets driven by code. Windows: NON PROVATO.
"""
import copy
import json
import re
import time
import traceback
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pypdfium2 as pdfium
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgb
from pypdfium2 import raw

from . import i18n
from .data import Dataset, load_workspace
from .field_error import FieldError
from .global_custom_fit import GLOBAL_CUSTOM_EQUATION
from .global_uncertainty import GID
from .graph_dialog import GraphFormatDialog
from .presentation import Layout, graph_series
from .workbench import analyse
from .windows_dpi import window_dpi

DATA = Path(__file__).resolve().parents[1] / "tests" / "data" / "global_uncertainty"
MAIN, DECAY, RATIONAL, EMPTY, PERFECT, BUDGET, MANY = (
    "Response demo", "Response decay", "Response rational", "Response empty label", "Response perfect",
    "Response budget", "Response many queries")
FIXED = "Response fixed"
RESPONSE = ("Curve band", "Response level (%)", "Band drawing", "Predict responses", "Query X", "Query group",
            "Query interval", "Query replicate count", "Allow extrapolation")
NEW_SHEETS = ["Curve bands", "Curve band settings", "Predictions"]
OLD_SHEETS = ["Parameters", "Global fit", "Covariance", "Residuals", "Curve"]


def fixture(name):
    return pd.DataFrame(json.loads((DATA / f"{name}.json").read_text()))


def pdf_counts(path):
    with pdfium.PdfDocument(path) as document:
        images = paths = 0
        for page in document:
            try:
                images += len(list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])))
                paths += len(list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH])))
            finally:
                page.close()
    return images, paths


def check_global_uncertainty(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, capture, pick_method, wait_for_calculation, messagebox, filedialog
    and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    expected = json.loads((DATA / "expected.json").read_text())
    recipes = json.loads((DATA / "recipes.json").read_text())
    out = directory / "global-uncertainty"
    out.mkdir(exist_ok=True)
    log = []
    previous_geometry = root.geometry()
    # Baseline dimensions are logical 100%-DPI pixels. Native Windows scaling
    # needs the corresponding physical viewport; no tk scaling is emulated.
    factor = window_dpi(root).get("window_dpi", 96) / 96
    minimum = tuple(round(value * factor) for value in (1024, 768))
    screen_pixels = (root.winfo_screenwidth(), root.winfo_screenheight())
    viewport = tuple(min(a, b) for a, b in zip(minimum, screen_pixels))
    root.geometry(f"{viewport[0]}x{viewport[1]}+0+0")
    root.update()
    app.tables[MAIN] = Dataset(fixture("linear-shared"))
    app.tables[DECAY] = Dataset(fixture("decay-shared"))
    app.tables[RATIONAL] = Dataset(fixture("rational-domain"))
    app.tables[EMPTY] = Dataset(fixture("linear-empty-label"))
    app.tables[PERFECT] = Dataset(fixture("linear-perfect"))
    parts = [pd.DataFrame({"X": np.arange(6, dtype=float), "Group": f"G{j}",
                           "Y": 2 + j + np.arange(6.) + .1 * np.arange(6.) ** 2 + np.sin(np.arange(6.)) * .02})
             for j in range(12)]
    app.tables[BUDGET] = Dataset(pd.concat(parts, ignore_index=True))
    many = fixture("linear-shared")[["Group", "X", "Y"]]
    many = pd.concat([many, pd.DataFrame({"Query X": np.ones(10_001), "Query group": "A"})], ignore_index=True)
    app.tables[MANY] = Dataset(many)
    app.refresh_navigator()

    def note(text):
        log.append(text)

    def shot(window, name):
        tools.capture(window, name)
        source = directory / name
        if source.exists():
            source.replace(out / name)

    def find(kind, parent=None, match=None):
        for child in (parent or root).winfo_children():
            if isinstance(child, kind) and (match is None or match(child)):
                return child
            found = find(kind, child, match)
            if found is not None:
                return found

    def drive(action, *, accept, kind=None, match=None):
        kind = kind or tools.AnalysisDialog
        state = {"done": False}

        def enter(tries=0):
            dialog = find(kind, match=match)
            if dialog is None or not dialog.winfo_viewable():
                if tries < 400:
                    root.after(30, lambda: enter(tries + 1))
                    return
                errors.append(f"{kind.__name__} did not open")
                state["done"] = True
                return
            try:
                dialog.update_idletasks()
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(f"{error!r}\n{traceback.format_exc()}")
                try:
                    dialog.cancel()
                except Exception:
                    pass
            state["done"] = True

        root.after(60, enter)
        return state

    def settle(state):
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "the dialog or the calculation did not finish"
            root.update()
            time.sleep(0.02)
        assert not errors, errors

    def menu_entry(menu_label, entry_label):
        # The menu bar keeps the language it was built with; dialogs follow the current one.
        bar = root.nametowidget(root.cget("menu"))
        for position in range(bar.index("end") + 1):
            if bar.type(position) == "cascade" and bar.entrycget(position, "label") in (menu_label, i18n.ui(menu_label)):
                popup = root.nametowidget(bar.entrycget(position, "menu"))
                for item in range(popup.index("end") + 1):
                    if popup.type(item) == "command" and popup.entrycget(item, "label") in (entry_label, i18n.ui(entry_label)):
                        return popup, item
        raise AssertionError(f"menu entry {menu_label} / {entry_label} not found")

    def control(dialog, name):
        return dialog.controls[name][1]

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot_name=None, contains=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (contains or field) in message, (field, message)
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        focus = dialog.focus_get()
        assert focus is not None and str(focus).startswith(str(dialog.field_rows[field][1])), (field, focus)
        if shot_name:
            dialog.update()
            # Where the app placed it, not moved by on_screen: still inside the screen.
            assert dialog.winfo_x() + dialog.winfo_width() <= root.winfo_screenwidth(), dialog.winfo_x()
            assert dialog.winfo_y() + dialog.winfo_height() <= root.winfo_screenheight(), dialog.winfo_y()
            shot(dialog, shot_name)
        note(f"rejected {field}: {message}")
        return message

    def buttons(dialog):
        found = []

        def walk(widget):
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                walk(child)

        walk(dialog)
        return found

    def on_screen(dialog, limit=None):
        limit = viewport if limit is None else limit
        dialog.geometry("+0+0")
        dialog.update()
        width, height = dialog.winfo_width(), dialog.winfo_height()
        assert width <= limit[0] and height <= limit[1], (width, height)
        labels = {widget.cget("text"): widget for widget in buttons(dialog)}
        for name in ("Run Analysis", "Cancel"):
            widget = labels[i18n.ui(name)]
            assert widget.winfo_viewable(), name
            assert widget.winfo_rooty() + widget.winfo_height() <= limit[1], name
        page = dialog.field_rows["Curve band"][1].master
        dialog.fields.select(page)
        dialog.update()
        bottom = dialog.fields.winfo_rooty() + dialog.fields.winfo_height()
        for name in RESPONSE:
            if placed(dialog, name):
                widget = dialog.field_rows[name][1]
                assert widget.winfo_rooty() + widget.winfo_height() <= bottom, name
        noted = dialog.global_response_note
        assert noted.winfo_rooty() + noted.winfo_height() <= bottom

    def prepare(dialog, points="21"):
        tools.pick_method(dialog, GLOBAL_CUSTOM_EQUATION)
        control(dialog, "X").set("X")
        control(dialog, "Y").set("Y")
        control(dialog, "Group").set("Group")
        control(dialog, "Curve points").set(points)
        dialog.global_series.refresh_labels()

    def response(dialog, **values):
        for name, value in values.items():
            control(dialog, name).set(value)
        dialog.update_idletasks()

    def fit_new(title, action):
        app.show("data", title)
        root.update()
        before = len(app.runs)
        state = drive(action, accept=True)
        popup, item = menu_entry("Analyze", "Analyze data…")
        popup.invoke(item)
        settle(state)
        wait()
        assert len(app.runs) == before + 1 and not errors, errors
        return before

    def edit(index, action, *, accept=True):
        app.show("result", index)
        root.update()
        state = drive(action, accept=accept)
        app.edit_analysis()
        settle(state)
        wait()

    def sheet(index, name):
        return app.runs[index].result.tables[name]

    def show_sheet(index, name):
        app.show("result", index)
        app.result_tabs.select(list(app.runs[index].result.tables).index(name))
        root.update()

    def band_collections(index):
        axes = app.runs[index].result.figure.axes[0]
        return {c.get_gid(): c for c in axes.collections if str(c.get_gid() or "").startswith(GID)}

    def band_color(collection):
        if isinstance(collection, PolyCollection):
            return tuple(collection.get_facecolor()[0, :3])
        return tuple(collection.get_colors()[0, :3])

    def signature(index):
        return [(s.key, s.kind) for s in graph_series(app.runs[index].result.figure.axes[0])]

    def assert_bands(index, case, kind):
        table = sheet(index, "Curve bands")
        reference = expected[case]["curves"]
        assert len(table) == len(reference), (len(table), len(reference))
        for group in dict.fromkeys(row["Group"] for row in reference):
            actual = table[table["Group"] == group]
            rows = [row for row in reference if row["Group"] == group]
            for column, key in (("X", "X"), ("Predicted", "Predicted"), ("SE mean", "SE mean"),
                                ("Lower", f"{kind} lower"), ("Upper", f"{kind} upper")):
                np.testing.assert_allclose(actual[column], [row[key] for row in rows], rtol=3e-6, atol=0)
        assert set(table["Status"]) == {"OK"}

    def assert_queries(index, case, interval, extrapolate=False):
        table = sheet(index, "Predictions")
        reference = expected[case]["queries"]
        assert len(table) == len(reference)
        for row in reference:
            actual = table[table["Source row"] == row["Source row"]].iloc[0]
            status = "Extrapolated" if (row["Status"] == "Outside domain" and extrapolate) else row["Status"]
            assert actual["Status"] == status, (case, row["Source row"], actual["Status"], status)
            if status in ("OK", "Extrapolated") and interval != "None":
                np.testing.assert_allclose(
                    actual[["Predicted", "SE mean", "Lower", "Upper"]].to_numpy(float),
                    [row["Predicted"], row["SE mean"], row[f"{interval} lower"], row[f"{interval} upper"]],
                    rtol=3e-6, atol=0)
            elif status not in ("OK", "Extrapolated"):
                assert pd.isna(actual["Predicted"]) and str(actual["Reason"]).strip(), actual
        return table

    # ---- A. Creation, field errors and correction without losing the other values -------------------------
    plain_index = fit_new(MAIN, lambda dialog: prepare(dialog))
    plain = app.runs[plain_index]
    assert list(plain.result.tables) == OLD_SHEETS, list(plain.result.tables)
    assert not any(key in plain.options for key in ("Curve band", "Predict responses")), plain.options
    plain_signature = signature(plain_index)
    note(f"A0 band off: five sheets, recipe keys {sorted(plain.options)}")

    def create(dialog):
        prepare(dialog)
        tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
        assert tabs == ["Variables", "Equation", "Parameters", "Series constraints", "Output", "Response"], tabs
        equation = control(dialog, "Equation").values()
        parameters = control(dialog, "Parameters").values()
        assert [name for name in RESPONSE if placed(dialog, name)] == ["Curve band", "Predict responses"]
        response(dialog, **{"Curve band": "Confidence"})
        assert placed(dialog, "Band drawing") and placed(dialog, "Response level (%)")
        for value in ("0", "100", "abc", "inf"):
            response(dialog, **{"Response level (%)": value})
            rejected(dialog, "Response level (%)",
                     shot_name="window-response-level-error.png" if value == "0" else None)
        response(dialog, **{"Response level (%)": "90", "Predict responses": True})
        assert all(placed(dialog, name) for name in ("Query X", "Query group", "Query interval",
                                                     "Allow extrapolation"))
        assert not placed(dialog, "Query replicate count")
        rejected(dialog, "Query X")
        response(dialog, **{"Query X": "Query X"})
        rejected(dialog, "Query group")
        response(dialog, **{"Query group": "Query X"})
        rejected(dialog, "Query group", contains="different column")
        response(dialog, **{"Query group": "Query group", "Query interval": "Prediction",
                            "Query replicate count": "Query X"})
        assert placed(dialog, "Query replicate count")
        rejected(dialog, "Query replicate count")
        response(dialog, **{"Query replicate count": "", "Query interval": "Confidence"})
        assert not placed(dialog, "Query replicate count")
        assert control(dialog, "Equation").values() == equation
        assert control(dialog, "Parameters").values() == parameters
        assert control(dialog, "Confidence level (%)").get() in ("95.0", "95")
        on_screen(dialog)
        shot(dialog, "window-response-dialog.png")

    index = fit_new(MAIN, create)
    run = app.runs[index]
    assert list(run.result.tables) == OLD_SHEETS + NEW_SHEETS, list(run.result.tables)
    assert run.options["Confidence level (%)"] == 95.0 and run.options["Response level (%)"] == 90.0
    for key in ("Curve band", "Band drawing", "Query interval"):
        assert run.options[key] in ("None", "Confidence", "Prediction", "Filled", "Lines"), run.options[key]
    assert_bands(index, "linear-shared", "Confidence")
    assert_queries(index, "linear-shared", "Confidence")
    params = sheet(index, "Parameters")
    np.testing.assert_allclose(params.loc[params["Scope"] == "Local", "Estimate"], [.98, 3.64], rtol=1e-9)
    assert signature(index) == plain_signature
    bands = band_collections(index)
    assert set(bands) == {GID + "A", GID + "B"} and all(isinstance(c, PolyCollection) for c in bands.values())
    note("A1 Confidence 90% Filled: 8 sheets, bands and queries match expected.json; coefficient level stays 95")
    app.show("graph", index)
    root.update()
    shot(root, "window-response-confidence-filled.png")
    show_sheet(index, "Curve bands")
    shot(root, "window-response-curve-bands.png")

    # SD weights: a band names Curve band, a query interval names Query interval, points still work.
    def weighted(dialog):
        prepare(dialog)
        response(dialog, Weighting="Inverse variance (column)")
        response(dialog, **{"SD column": "SD", "Curve band": "Prediction"})
        rejected(dialog, "Curve band", contains="Unweighted")
        response(dialog, **{"Curve band": "None", "Predict responses": True, "Query X": "Query X",
                            "Query group": "Query group", "Query interval": "Confidence"})
        rejected(dialog, "Query interval", contains="Unweighted")
        response(dialog, **{"Query interval": "None"})

    weighted_index = fit_new(MAIN, weighted)
    weighted_table = sheet(weighted_index, "Predictions")
    assert weighted_table["Lower"].isna().all() and weighted_table["Predicted"].notna().sum() == 5
    note("A2 SD weights: Curve band and Query interval errors on their fields; point predictions computed")

    # Budget and query limit stop in the dialog, before the worker.
    def budget(dialog):
        prepare(dialog, points="10000")
        response(dialog, **{"Curve band": "Confidence"})
        dialog.controls["Equation"][1].box.delete("1.0", "end")
        dialog.controls["Equation"][1].box.insert("1.0", "A+B*X+C*X^2")
        table = control(dialog, "Parameters")
        table.rows.clear()
        table.from_equation()
        rejected(dialog, "Curve points", contains="uncertainty budget")
        response(dialog, **{"Curve points": "1000"})

    budget_index = fit_new(BUDGET, budget)
    assert len(sheet(budget_index, "Curve bands")) == 12 * 1000

    def limit(dialog):
        prepare(dialog)
        response(dialog, **{"Predict responses": True, "Query X": "Query X", "Query group": "Query group"})
        rejected(dialog, "Query X", contains="10,000")
        dialog.result = None

    app.show("data", MANY)
    root.update()
    state = drive(limit, accept=False)
    popup, item = menu_entry("Analyze", "Analyze data…")
    popup.invoke(item)
    settle(state)
    note("A3 budget names Curve points (12 series × 10000 points × 36 free); 10,001 query rows name Query X")

    # ---- B. Bands and queries follow the one fit -----------------------------------------------------------
    centre = sheet(index, "Curve bands")["Predicted"].to_numpy()
    narrow = (sheet(index, "Curve bands")["Upper"] - sheet(index, "Curve bands")["Lower"]).to_numpy()

    def to_prediction(dialog):
        response(dialog, **{"Curve band": "Prediction", "Band drawing": "Lines", "Query interval": "Prediction",
                            "Query replicate count": "Query k"})

    edit(index, to_prediction)
    assert_bands(index, "linear-shared", "Prediction")
    assert_queries(index, "linear-shared", "Prediction")
    table = sheet(index, "Curve bands")
    np.testing.assert_array_equal(table["Predicted"].to_numpy(), centre)
    assert ((table["Upper"] - table["Lower"]).to_numpy() > narrow).all()
    queries = sheet(index, "Predictions").set_index("Source row")
    assert queries.loc[0, "SE mean"] == queries.loc[8, "SE mean"]
    assert queries.loc[8, "Upper"] - queries.loc[8, "Lower"] < queries.loc[0, "Upper"] - queries.loc[0, "Lower"]
    assert list(queries["k"].iloc[:2]) == [1.0, 4.0]
    for name in OLD_SHEETS:
        pd.testing.assert_frame_equal(sheet(index, name), plain.result.tables[name] if name != "Global fit"
                                      else sheet(index, name))
    pd.testing.assert_frame_equal(sheet(index, "Parameters"), plain.result.tables["Parameters"])
    bands = band_collections(index)
    assert all(isinstance(c, LineCollection) for c in bands.values()) and signature(index) == plain_signature
    app.show("graph", index)
    root.update()
    shot(root, "window-response-prediction-lines.png")
    note("B1 Prediction Lines: same centre, wider band; k=4 narrower with the same SE mean; band stays k=1")

    def extrapolate(dialog):
        response(dialog, **{"Allow extrapolation": True})

    assert sheet(index, "Predictions").loc[4, "Status"] == "Outside domain"
    edit(index, extrapolate)
    assert_queries(index, "linear-shared", "Prediction", extrapolate=True)
    assert bool(sheet(index, "Predictions").loc[4, "Extrapolated"])
    show_sheet(index, "Predictions")
    shot(root, "window-response-predictions.png")
    note("B2 X=4.5 for series A: Outside domain, then Extrapolated (domain of A is 0..4, B is 0..6)")

    # The other fixtures through the same dialog.
    def decay(dialog):
        prepare(dialog)
        box = dialog.controls["Equation"][1].box
        box.delete("1.0", "end")
        box.insert("1.0", "A*exp(-K*X)+C")
        table = control(dialog, "Parameters")
        table.rows.clear()
        table.from_equation()
        for name, scope, start in (("A", "Local", 5), ("K", "Shared", .3), ("C", "Fixed", 0)):
            position = next(i for i, row in enumerate(table.rows) if row["name"] == name)
            table.tree.selection_set(str(position))
            table.load_selection()
            table.scope.set(scope)
            table.variables["start"].set(str(start))
            if name == "K":
                table.variables["lower"].set("0")
        response(dialog, **{"Curve band": "Confidence", "Response level (%)": "90", "Predict responses": True,
                            "Query X": "Query X", "Query group": "Query group", "Query interval": "Confidence"})

    decay_index = fit_new(DECAY, decay)
    assert_bands(decay_index, "decay-shared", "Confidence")
    assert_queries(decay_index, "decay-shared", "Confidence")
    covariance = sheet(decay_index, "Covariance").to_numpy(float)
    assert covariance.shape == (3, 3) and abs(covariance[0, 1]) > 0 and abs(covariance[1, 2]) > 0
    note("B3 decay-shared: K shared with A local per series; full covariance; matches expected.json")

    def rational(dialog):
        prepare(dialog)
        box = dialog.controls["Equation"][1].box
        box.delete("1.0", "end")
        box.insert("1.0", "A/(1+B*X)")
        table = control(dialog, "Parameters")
        table.rows.clear()
        table.from_equation()
        for name, scope, start in (("A", "Shared", 2), ("B", "Fixed", 1)):
            position = next(i for i, row in enumerate(table.rows) if row["name"] == name)
            table.tree.selection_set(str(position))
            table.load_selection()
            table.scope.set(scope)
            table.variables["start"].set(str(start))
        response(dialog, **{"Predict responses": True, "Query X": "Query X", "Query group": "Query group",
                            "Query interval": "Prediction", "Query replicate count": "Query k",
                            "Response level (%)": "90", "Allow extrapolation": True})

    rational_index = fit_new(RATIONAL, rational)
    statuses = sheet(rational_index, "Predictions")["Status"].tolist()
    assert statuses == ["Undefined model", "Extrapolated", "OK"], statuses
    note("B4 rational-domain: X=-1 Undefined model, X=-0.5 Extrapolated, X=1 OK, one fit")

    def empty_label(dialog):
        prepare(dialog)
        response(dialog, **{"Curve band": "Confidence", "Response level (%)": "90", "Predict responses": True,
                            "Query X": "Query X", "Query group": "Query group", "Query interval": "Confidence"})

    empty_index = fit_new(EMPTY, empty_label)
    assert_bands(empty_index, "linear-empty-label", "Confidence")
    empty_table = assert_queries(empty_index, "linear-empty-label", "Confidence")
    assert empty_table.loc[0, "Group"] == "" and empty_table.loc[7, "Group"] is None
    assert GID in band_collections(empty_index)
    note("B5 empty label '' is a fitted series (gid 'trama-global-band:'); null query group is Missing group")

    def perfect(dialog):
        prepare(dialog)
        response(dialog, **{"Curve band": "Prediction", "Predict responses": True, "Query X": "Query X",
                            "Query group": "Query group", "Query interval": "Prediction"})

    perfect_index = fit_new(PERFECT, perfect)
    perfect_bands = sheet(perfect_index, "Curve bands")
    assert perfect_bands["Lower"].isna().all() and (perfect_bands["Status"] == "Unavailable").all()
    assert not band_collections(perfect_index)
    unavailable = sheet(perfect_index, "Predictions")
    unavailable = unavailable[unavailable["Status"] == "Interval unavailable"]
    assert len(unavailable) and unavailable["Predicted"].notna().all()
    note("B6 perfect fit: curve and point predictions kept, no interval and no zero-width band drawn")

    def coefficients(dialog, rows, fixes=()):
        table = control(dialog, "Parameters")
        for name, scope, start, upper in rows:
            position = next(i for i, row in enumerate(table.rows) if row["name"] == name)
            table.tree.selection_set(str(position))
            table.load_selection()
            table.scope.set(scope)
            table.variables["start"].set(str(start))
            table.variables["upper"].set("" if upper is None else str(upper))
        editor = dialog.global_series
        for label, name, value in fixes:
            editor.select_series(label)
            editor.select_coefficient(name)
            editor.variables["fixed"].set(str(value))

    def fixed_case(dialog):
        prepare(dialog)
        coefficients(dialog, (("A", "Local", 1, None), ("B", "Shared", 1, None)), fixes=(("B", "A", 3.6),))
        response(dialog, **{"Curve band": "Confidence", "Response level (%)": "90", "Predict responses": True,
                            "Query X": "Query X", "Query group": "Query group", "Query interval": "Confidence"})

    app.tables[FIXED] = Dataset(fixture("linear-fixed"))
    app.refresh_navigator()
    fixed_index = fit_new(FIXED, fixed_case)
    assert app.runs[fixed_index].options["Series constraints"] == recipes["linear-fixed"]["Series constraints"]
    assert_bands(fixed_index, "linear-fixed", "Confidence")
    assert_queries(fixed_index, "linear-fixed", "Confidence")
    assert sheet(fixed_index, "Covariance").shape == (2, 2)
    note("B7 linear-fixed: A of series B fixed at 3.6 in Series constraints stays fixed (2x2 covariance); "
         "matches expected.json")

    for case, rows in (("all-fixed", (("A", "Fixed", 1, None), ("B", "Fixed", 1.5, None))),
                       ("active-bound", (("A", "Local", 1, None), ("B", "Shared", .1, .2)))):
        title = "Response " + case
        app.tables[title] = Dataset(fixture(case))
        app.refresh_navigator()

        def unavailable_case(dialog, rows=rows):
            prepare(dialog)
            coefficients(dialog, rows)
            response(dialog, **{"Curve band": "Prediction", "Predict responses": True, "Query X": "Query X",
                                "Query group": "Query group", "Query interval": "Prediction"})

        position = fit_new(title, unavailable_case)
        bands_table = sheet(position, "Curve bands")
        assert bands_table["Predicted"].notna().all() and bands_table["Lower"].isna().all()
        assert (bands_table["Reason"].str.len() > 0).all() and not band_collections(position)
        queries = sheet(position, "Predictions")
        assert queries.loc[queries["Status"] == "Interval unavailable", "Predicted"].notna().all()
        note(f"B8 {case}: curve and point predictions kept, reason '{bands_table['Reason'].iloc[0]}', no band drawn")

    # ---- C. Recalculation, exclusions, Cancel and a late error from the worker ----------------------------
    columns = list(app.tables[MAIN].raw.columns)
    before = sheet(index, "Parameters")["Estimate"].to_numpy()
    before_bands = sheet(index, "Curve bands")["Upper"].to_numpy()
    app.show("data", MAIN)
    root.update()
    app.edit_cell(0, columns.index("Y"), "1.3")
    wait()
    after = sheet(index, "Parameters")["Estimate"].to_numpy()
    assert np.abs(after - before).max() > 1e-3
    assert np.abs(sheet(index, "Curve bands")["Upper"].to_numpy() - before_bands).max() > 1e-3
    note("C1 edited Y of the fit: estimates, bands and queries recalculated")
    app.show("data", MAIN)
    root.update()
    app.current_grid.select((2, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    summary = sheet(index, "Global fit")
    assert int(summary.loc["Observations", "Value"]) == 8 and int(summary.loc["DF residual", "Value"]) == 5
    assert 2 not in sheet(index, "Residuals")["Source row"].tolist()
    assert sheet(index, "Curve band settings")["df"].tolist() == [5, 5]
    note("C2 excluded Y: N 9 -> 8, df 6 -> 5 in Global fit and Curve band settings")
    fit_before = {name: sheet(index, name).copy() for name in ("Parameters", "Global fit", "Covariance")}
    predicted = sheet(index, "Predictions").loc[0, "Predicted"]
    app.show("data", MAIN)
    root.update()
    app.edit_cell(0, columns.index("Query X"), "2")
    wait()
    for name, frame in fit_before.items():
        pd.testing.assert_frame_equal(sheet(index, name), frame)
    assert sheet(index, "Predictions").loc[0, "Predicted"] != predicted
    note("C3 edited Query X only: Parameters, Global fit and Covariance identical; the query changed")
    app.show("data", MAIN)
    root.update()
    app.current_grid.select((3, columns.index("Query X")))
    app.toggle_exclusion()
    wait()
    excluded = sheet(index, "Predictions")
    assert excluded.loc[excluded["Source row"] == 3, "Status"].iloc[0] == "Missing X"
    for name, frame in fit_before.items():
        pd.testing.assert_frame_equal(sheet(index, name), frame)
    note("C4 excluded Query X with its group present: Missing X on Source row 3, fit unchanged")

    confirmed = app.runs[index]
    confirmed_options = copy.deepcopy(confirmed.options)
    confirmed_figure = confirmed.result.figure

    def change_and_cancel(dialog):
        response(dialog, **{"Curve band": "None", "Predict responses": False})

    edit(index, change_and_cancel, accept=False)
    assert app.runs[index] is confirmed and confirmed.options == confirmed_options
    assert confirmed.result.figure is confirmed_figure
    note("C5 Cancel on a confirmed analysis: options, result and figure unchanged")

    def rank_deficient(dialog):
        box = dialog.controls["Equation"][1].box
        box.delete("1.0", "end")
        box.insert("1.0", "A+B*X+C*X")
        table = control(dialog, "Parameters")
        table.from_equation()
        response(dialog, **{"Query interval": "Confidence", "Response level (%)": "80"})

    def recovered(dialog):
        assert dialog.error_label is not None and "identifiable" in dialog.error_label.cget("text")
        assert dialog.fields.select() == str(dialog.field_rows["Parameters"][1].master)
        assert dialog.controls["Equation"][1].values() == "A+B*X+C*X"
        assert control(dialog, "Query interval").get() == "Confidence"
        assert float(control(dialog, "Response level (%)").get()) == 80
        dialog.update()
        shot(dialog, "window-response-recovered.png")

    app.show("result", index)
    root.update()
    state = drive(rank_deficient, accept=True)
    # The reopened dialog is modal inside the event loop, so its driver must be waiting already.
    recovery = drive(recovered, accept=False, match=lambda d: getattr(d, "error_label", None) is not None)
    app.edit_analysis()
    settle(state)
    settle(recovery)
    assert app.runs[index] is confirmed and confirmed.options == confirmed_options
    assert "discarded" in app.status.get(), app.status.get()
    note("C6 real worker failure (A+B*X+C*X is rank deficient): the candidate reopens on Parameters with "
         "the typed response fields; Cancel keeps the confirmed analysis")

    def query_candidate(dialog):
        response(dialog, **{"Allow extrapolation": False})

    def query_recovered(dialog):
        assert "Injected" in dialog.error_label.cget("text")
        assert dialog.fields.select() == str(dialog.field_rows["Query X"][1].master)
        assert control(dialog, "Allow extrapolation").get() is False

    app.show("result", index)
    state = drive(query_candidate, accept=True)
    with patch("analisi.global_uncertainty.prediction_table", side_effect=FieldError("Query X", "Injected query failure")):
        recovery = drive(query_recovered, accept=False, match=lambda d: getattr(d, "error_label", None) is not None)
        app.edit_analysis()
        settle(state)
        settle(recovery)
    assert app.runs[index] is confirmed
    note("C6b injected FieldError on Query X (mechanism only): reopens on the Response page, Cancel keeps it")

    # ---- D. Styles: Format Graph, Inspector, Reset, visibility ----------------------------------------------
    def series_lines(position):
        return [s for s in graph_series(app.runs[position].result.figure.axes[0]) if s.kind == "line"]

    def format_graph(position, action):
        app.show("graph", position)
        root.update()
        state = drive(action, accept=True, kind=GraphFormatDialog)
        app.format_graph()
        settle(state)

    def color_line(number, color):
        def action(dialog):
            series = [i for i, s in enumerate(dialog.series) if s.kind == "line"][number]
            dialog.series_selector.current(series)
            dialog._select_series()
            dialog.series_fields["color"].set(color)
        return action

    format_graph(index, color_line(0, "#9d2f75"))
    bands = band_collections(index)
    assert np.allclose(band_color(bands[GID + "A"]), to_rgb("#9d2f75")), band_color(bands[GID + "A"])
    assert not np.allclose(band_color(bands[GID + "B"]), to_rgb("#9d2f75"))
    shot(root, "window-response-style-format.png")
    app.show("graph", index)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    keys = [item["key"] for item in panel.elements]
    line_b = series_lines(index)[1].key
    assert panel.select_group(line_b), keys
    widget = panel.fields["color"]["widget"]
    panel.vars["element:color"].set("#9d2f75")
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert np.allclose(band_color(bands[GID + "B"]), to_rgb("#9d2f75")), "Inspector preview"
    panel.discard()
    root.update()
    assert not np.allclose(band_color(bands[GID + "B"]), to_rgb("#9d2f75")), "Inspector discard"
    assert panel.select_group(line_b)
    panel.vars["element:color"].set("#1b7a3e")
    widget.focus_force()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert np.allclose(band_color(bands[GID + "B"]), to_rgb("#1b7a3e"))
    assert np.allclose(band_color(bands[GID + "A"]), to_rgb("#9d2f75"))
    shot(root, "window-response-style-inspector.png")
    svg = out / "inspector-open.svg"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(svg)):
        app.export()
    app.toggle_inspector()
    root.update()
    text = svg.read_text(encoding="utf-8")
    assert text.count('id="trama-global-band:') == 2, "bands in the SVG"
    assert "inspector" not in text.lower()
    note("D1 Format Graph colours line A and its band; Inspector previews, discards and applies B; "
         "export with the Inspector open has no selection or panel elements")

    def same_color(dialog):
        color_line(1, "#9d2f75")(dialog)

    format_graph(index, same_color)
    assert np.allclose(band_color(bands[GID + "B"]), to_rgb("#9d2f75"))

    def hide_a(dialog):
        color_line(0, "#9d2f75")(dialog)
        dialog.series_fields["line_style"].set("none")

    format_graph(index, hide_a)
    assert not bands[GID + "A"].get_visible() and bands[GID + "B"].get_visible()
    shot(root, "window-response-hidden-line.png")

    def show_a(dialog):
        dialog.series_selector.current([i for i, s in enumerate(dialog.series) if s.kind == "line"][0])
        dialog._select_series()
        dialog.series_fields["line_style"].set("solid")

    format_graph(index, show_a)
    assert bands[GID + "A"].get_visible()

    def reset(dialog):
        dialog._reset()

    app.show("graph", index)
    root.update()
    state = drive(reset, accept=False, kind=GraphFormatDialog)
    app.format_graph()
    settle(state)
    lines = series_lines(index)
    for line, gid in zip(lines, (GID + "A", GID + "B")):
        assert np.allclose(band_color(bands[gid]), to_rgb(line.artist.get_color())), gid
    assert not app.runs[index].style, app.runs[index].style
    note("D2 same colour on both fits keeps each band on its own line; hiding line A hides band A only; "
         "restoring shows it; Reset returns both bands to the default colours")
    format_graph(index, color_line(0, "#9d2f75"))
    format_graph(index, color_line(1, "#1b7a3e"))
    styled = copy.deepcopy(app.runs[index].style)
    assert "trama-global-band" not in json.dumps(styled)

    # Fixed Y limits are formatting only: no new solve, same tables, same band geometry and alpha.
    def y_limits(dialog):
        dialog.axis_fields["y"]["min"].set("-2")
        dialog.axis_fields["y"]["max"].set("16")

    tables_before = {name: frame.copy() for name, frame in app.runs[index].result.tables.items()}
    geometry_before = {gid: ([path.vertices.copy() for path in c.get_paths()], c.get_alpha())
                       for gid, c in band_collections(index).items()}
    with patch("analisi.global_custom_fit._solve") as solve:
        format_graph(index, y_limits)
    solve.assert_not_called()
    assert tuple(app.runs[index].result.figure.axes[0].get_ylim()) == (-2., 16.)
    for name, frame in tables_before.items():
        pd.testing.assert_frame_equal(app.runs[index].result.tables[name], frame)
    for gid, collection in band_collections(index).items():
        paths, alpha = geometry_before[gid]
        assert collection.get_alpha() == alpha, gid
        assert all(np.array_equal(a, b.vertices) for a, b in zip(paths, collection.get_paths())), gid
    shot(root, "window-response-y-limits.png")
    note("D3 fixed Y limits -2..16 in Format Graph: no new solve, result tables and band paths/alpha unchanged")

    # ---- E. Save, reopen graph first, legacy project, Use Result as Data, exports, layout ----------------
    filled_index = fit_new(MAIN, lambda dialog: (prepare(dialog), response(
        dialog, **{"Curve band": "Confidence", "Band drawing": "Filled", "Response level (%)": "90"})))
    layout = Layout("Response panels", 2, [app.runs[filled_index].reference, app.runs[index].reference])
    app.layouts.append(layout)
    app.show("layout", len(app.layouts) - 1)
    root.update()
    shot(root, "window-response-layout.png")
    for suffix in ("pdf", "svg"):
        target = out / f"response-layout.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    images, paths = pdf_counts(out / "response-layout.pdf")
    assert images == 0 and paths > 0, (images, paths)
    layout_svg = (out / "response-layout.svg").read_text(encoding="utf-8")
    assert "<image" not in layout_svg and layout_svg.count("<path") > 20
    note(f"E4 two-panel layout (Filled + Lines): PDF {paths} vector paths and no image; SVG without <image>")

    for suffix in ("svg", "png", "pdf"):
        target = out / f"response-graph.{suffix}"
        app.show("graph", index)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    graph_svg = (out / "response-graph.svg").read_text(encoding="utf-8")
    assert graph_svg.count('id="trama-global-band:') == 2 and "<image" not in graph_svg
    images, paths = pdf_counts(out / "response-graph.pdf")
    assert images == 0 and paths > 0, (images, paths)
    for name, file in (("Predictions", "predictions.csv"), ("Curve bands", "curve-bands.csv")):
        show_sheet(index, name)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(out / file)):
            app.export()
        exported = pd.read_csv(out / file, encoding="utf-8-sig", keep_default_na=False, na_values=[""], index_col=0)
        assert list(exported.columns)[:8] == list(sheet(index, name).columns)[:8], exported.columns
        assert len(exported) == len(sheet(index, name))
    note("E4 graph SVG/PDF vector with two band groups, PNG raster; Predictions and Curve bands CSV")

    created = set(app.tables)
    for name in ("Predictions", "Curve bands"):
        show_sheet(index, name)
        app.use_result_as_data()
    created = set(app.tables) - created
    frames = {name: app.tables[name].raw for name in created}
    assert any(list(frame.columns)[:2] == ["Source row", "Group"] and frame["Predicted"].isna().any()
               for frame in frames.values()), frames
    assert any(list(frame.columns)[:3] == ["Group", "X", "Predicted"] for frame in frames.values())
    note("E3 Use Result as Data from Predictions and Curve bands: full columns, missing kept, Source row kept")

    snapshots = {(item.title, item.slot): copy.deepcopy(item.options) for item in app.runs
                 if item.method == GLOBAL_CUSTOM_EQUATION}
    style_before = copy.deepcopy(app.runs[index].style)
    numbers = sheet(index, "Predictions").copy()
    title, slot = app.runs[index].title, app.runs[index].slot
    app.path = directory / "global-uncertainty.alab"
    assert app.save()
    payload = Path(app.path).read_text(encoding="utf-8")
    assert "trama-global-band" not in payload and "PolyCollection" not in payload
    app.import_file(app.path)
    position = next(i for i, item in enumerate(app.runs) if (item.title, item.slot) == (title, slot))
    app.open_sheet(("graph", position))
    wait()
    root.update()
    reopened = app.runs[position]
    assert reopened.options == snapshots[(title, slot)] and reopened.style == style_before
    bands = band_collections(position)
    assert np.allclose(band_color(bands[GID + "A"]), to_rgb("#9d2f75"))
    assert np.allclose(band_color(bands[GID + "B"]), to_rgb("#1b7a3e"))
    app.open_sheet(("result", position))
    wait()
    pd.testing.assert_frame_equal(reopened.result.tables["Predictions"], numbers, rtol=1e-10, atol=1e-12)
    shot(root, "window-response-reopened.png")
    note("E1 saved and reopened .alab, graph first: same options, style and colours; Predictions identical")

    app.import_file(DATA / "legacy-global-070.alab")
    legacy = [i for i, item in enumerate(app.runs) if item.method == GLOBAL_CUSTOM_EQUATION]
    assert legacy
    for position in legacy:
        app.open_sheet(("result", position))
        wait()
        assert list(app.runs[position].result.tables) == OLD_SHEETS
        assert not any(key in app.runs[position].options for key in RESPONSE)
    legacy_options = copy.deepcopy(app.runs[legacy[0]].options)

    def legacy_open(dialog):
        assert control(dialog, "Curve band").get() == "None"
        assert not control(dialog, "Predict responses").get()

    edit(legacy[0], legacy_open)
    assert app.runs[legacy[0]].options == legacy_options, app.runs[legacy[0]].options
    app.path = directory / "legacy-resaved.alab"
    assert app.save()
    _, tables = None, load_workspace(app.path)[0]
    for dataset in tables.values():
        for method, options in dataset.analyses:
            if method == GLOBAL_CUSTOM_EQUATION:
                assert not any(key in options for key in RESPONSE), options
    note("E2 legacy-global-070.alab: five sheets; Run Analysis with the new outputs off and Save add no keys")

    # ---- F. Italian, comma decimal, canonical recipe -------------------------------------------------------
    i18n.set_language("it")
    try:
        app.tables[MAIN] = Dataset(fixture("linear-shared"))
        app.refresh_navigator()

        def italian(dialog):
            prepare(dialog)
            page = dialog.field_rows["Curve band"][1].master
            assert dialog.fields.tab(page, "text") == "Bande e previsioni"
            assert dialog.field_rows["Response level (%)"][0].cget("text") == "Livello della risposta (%)"
            response(dialog, **{"Curve band": "Prediction", "Response level (%)": "0",
                                "Predict responses": True, "Query X": "Query X", "Query group": "Query group",
                                "Query interval": "Prediction", "Query replicate count": "Query k"})
            assert dialog.choice_bindings["Curve band"].combobox.get() == "Predizione (nuove osservazioni)"
            message = rejected(dialog, "Response level (%)", contains="Livello della risposta (%)")
            assert "strettamente" in message
            response(dialog, **{"Response level (%)": "90,0"})
            dialog.fields.select(page)
            on_screen(dialog)
            shot(dialog, "window-response-dialog-it.png")

        italian_index = fit_new(MAIN, italian)
        options = app.runs[italian_index].options
        assert options["Response level (%)"] == 90.0 and options["Curve band"] == "Prediction"
        assert options["Query interval"] == "Prediction" and options["Query replicate count"] == "Query k"
        assert_bands(italian_index, "linear-shared", "Prediction")
        assert_queries(italian_index, "linear-shared", "Prediction")
        note("F Italian dialog: 'Bande e previsioni', 90,0 accepted, recipe keeps canonical English keys/values")
    finally:
        i18n.set_language("en")

    screen = (root.winfo_screenwidth(), root.winfo_screenheight())
    wide_size = tuple(round(value * factor) for value in (1400, 900))
    if all(actual >= required for actual, required in zip(screen, wide_size)):
        root.geometry(f"{wide_size[0]}x{wide_size[1]}+0+0")
        root.update()

        def wide(dialog):
            prepare(dialog)
            response(dialog, **{"Curve band": "Confidence", "Predict responses": True, "Query X": "Query X",
                                "Query group": "Query group", "Query interval": "Prediction"})
            on_screen(dialog, limit=wide_size)
            shot(dialog, "window-response-dialog-wide.png")

        app.show("data", MAIN)
        root.update()
        state = drive(wide, accept=False)
        popup, item = menu_entry("Analyze", "Analyze data…")
        popup.invoke(item)
        settle(state)
        note(f"F wide window {screen[0]}x{screen[1]}: dialog checked at 1400x900")
    root.geometry(previous_geometry)
    root.update()
    (out / "smoke.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    assert not errors, errors
    assert i18n.active_language() == "en"
    assert app.pending is None
