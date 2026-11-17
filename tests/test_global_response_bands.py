"""Global fit custom equation, 0.70: pointwise response bands from the one joint fit.

Expected numbers are the independent oracles of tests/data/global_uncertainty/expected.json (exact
rational algebra for the straight lines, an analytic-Jacobian fit for the decays). Nothing here is
derived from the engine under test.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgb

from analisi import global_custom_fit as engine
from analisi import global_uncertainty as uncertainty
from analisi.field_error import FieldError
from analisi.presentation import apply_style, graph_series
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "global_uncertainty"
RECIPES = json.loads((DATA / "recipes.json").read_text())
EXPECTED = json.loads((DATA / "expected.json").read_text())
METHOD = engine.GLOBAL_CUSTOM_EQUATION


def frame(name):
    return pd.DataFrame(json.loads((DATA / f"{name}.json").read_text()))


def recipe(name, **more):
    options = copy.deepcopy(RECIPES[name])
    options.update({"Curve band": "Confidence", "Band drawing": "Filled", "Response level (%)": 90.})
    options.update(more)
    return options


def run(name, **more):
    return analyse(METHOD, frame(name), recipe(name, **more))


class BandNumbers(unittest.TestCase):
    def check(self, name, kind):
        result = run(name, **{"Curve band": kind})
        table = result.tables["Curve bands"]
        expected = EXPECTED[name]["curves"]
        self.assertEqual(len(table), len(expected))
        self.assertEqual(list(table.columns[:8]), uncertainty.BAND_COLUMNS)
        # Same grid, order and rows as Curve.
        pd.testing.assert_frame_equal(table[["Group", "X", "Predicted"]], result.tables["Curve"])
        for group in dict.fromkeys(row["Group"] for row in expected):
            actual = table[table["Group"] == group]
            reference = [row for row in expected if row["Group"] == group]
            for column, key in (("X", "X"), ("Predicted", "Predicted"), ("SE mean", "SE mean"),
                                ("Lower", f"{kind} lower"), ("Upper", f"{kind} upper")):
                with self.subTest(case=name, group=group, column=column):
                    np.testing.assert_allclose(actual[column], [row[key] for row in reference], rtol=3e-6, atol=0)
        self.assertEqual(set(table["Status"]), {"OK"})
        self.assertTrue((table["Reason"] == "").all())
        settings = result.tables["Curve band settings"]
        self.assertEqual(list(settings.columns[:8]), ["Group", "Band", "Level", "N", "df", "Available", "Status", "Reason"])
        self.assertTrue(settings["Available"].all())
        self.assertEqual(set(settings["df"]), {EXPECTED[name]["df"]})
        return result

    def test_every_independent_case(self):
        for name in ("linear-shared", "linear-fixed", "linear-small-y", "linear-empty-label",
                     "decay-shared", "decay-large-x"):
            for kind in ("Confidence", "Prediction"):
                self.check(name, kind)

    def test_full_covariance_differs_from_diagonal_only(self):
        result = run("linear-shared")
        covariance = result.tables["Covariance"].to_numpy(dtype=float)
        # Shared slope first in the engine, then each intercept: g = (X, 1, 0) for series A.
        x = 1.5
        g = np.array([x, 1., 0.])
        full, diagonal = g @ covariance @ g, (g * g) @ np.diag(covariance)
        band = result.tables["Curve bands"]
        self.assertGreater(abs(full - diagonal), .005)
        point = np.interp(x, band.loc[band["Group"] == "A", "X"], band.loc[band["Group"] == "A", "SE mean"] ** 2)
        self.assertAlmostEqual(point, full, delta=.02 * full)

    def test_level_changes_only_the_band(self):
        a, b = run("linear-shared"), run("linear-shared", **{"Response level (%)": 99.})
        for sheet in ("Parameters", "Global fit", "Covariance", "Residuals", "Curve"):
            pd.testing.assert_frame_equal(a.tables[sheet], b.tables[sheet])
        pd.testing.assert_series_equal(a.tables["Curve bands"]["SE mean"], b.tables["Curve bands"]["SE mean"])
        width = lambda r: (r.tables["Curve bands"]["Upper"] - r.tables["Curve bands"]["Lower"]).to_numpy()
        self.assertTrue((width(b) > width(a)).all())

    def test_one_joint_solve(self):
        with patch.object(engine, "_solve", wraps=engine._solve) as solve:
            run("decay-shared", **{"Curve band": "Prediction", "Band drawing": "Lines"})
        self.assertEqual(solve.call_count, 1)

    def test_comma_level_from_text(self):
        result = run("linear-shared", **{"Response level (%)": "90,0"})
        np.testing.assert_allclose(result.tables["Curve band settings"]["Level"], 90.)


class Availability(unittest.TestCase):
    def test_unavailable_cases_keep_the_curve(self):
        for name in ("linear-perfect", "all-fixed", "active-bound"):
            with self.subTest(case=name):
                result = run(name, **{"Curve band": "Prediction"})
                table = result.tables["Curve bands"]
                self.assertEqual(len(table), len(result.tables["Curve"]))
                self.assertTrue(table["Predicted"].notna().all())
                self.assertTrue(table[["SE mean", "Lower", "Upper"]].isna().all().all())
                self.assertTrue((table["Status"] == "Unavailable").all())
                self.assertTrue((table["Reason"].str.len() > 0).all())
                settings = result.tables["Curve band settings"]
                self.assertFalse(settings["Available"].any())
                self.assertEqual(set(settings["Status"]), {"Unavailable"})
                # No zero-width band is drawn.
                axes = result.figure.axes[0]
                self.assertFalse([c for c in axes.collections if str(c.get_gid()).startswith(uncertainty.GID)])

    def test_partial_band_keeps_gaps(self):
        drawn = [("A", np.arange(6.), np.array([0, 1, np.nan, 3, 4, 5.]), np.array([1, 2, np.nan, 4, 5, 6.]))]
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        axes = Figure().add_subplot()
        line, = axes.plot(np.arange(6.), np.arange(6.))
        uncertainty.draw_bands(axes, drawn, [line], uncertainty.FILLED)
        collection = axes.collections[0]
        self.assertEqual(len(collection.get_paths()), 2)


class Validation(unittest.TestCase):
    def field(self, name, field, data=None, **more):
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, frame(name) if data is None else data, recipe(name, **more))
        self.assertEqual(caught.exception.field, field)

    def test_levels(self):
        for value in (0, 100, 0., 100., float("nan"), float("inf"), True, "text", None):
            with self.subTest(value=value):
                self.field("linear-shared", "Response level (%)", **{"Response level (%)": value})

    def test_inactive_fields_are_not_read(self):
        legacy = copy.deepcopy(RECIPES["linear-shared"])
        old = analyse(METHOD, frame("linear-shared"), legacy)
        legacy.update({"Curve band": "None", "Response level (%)": "inactive", "Band drawing": "nonsense"})
        new = analyse(METHOD, frame("linear-shared"), legacy)
        self.assertEqual(list(new.tables), ["Parameters", "Global fit", "Covariance", "Residuals", "Curve"])
        for sheet in old.tables:
            pd.testing.assert_frame_equal(old.tables[sheet], new.tables[sheet])

    def test_bad_choices(self):
        self.field("linear-shared", "Curve band", **{"Curve band": "Simultaneous"})
        self.field("linear-shared", "Band drawing", **{"Band drawing": "Dots"})

    def test_sd_weights_refuse_the_band(self):
        self.field("linear-weighted", "Curve band")
        result = analyse(METHOD, frame("linear-weighted"), recipe("linear-weighted", **{"Curve band": "None"}))
        self.assertNotIn("Curve bands", result.tables)

    def test_budget_in_check_options(self):
        parts = []
        for j in range(12):
            x = np.arange(6, dtype=float)
            parts.append(pd.DataFrame({"X": x, "Y": 2 + j + x + .1 * x * x + np.sin(x) * .02, "Group": f"G{j}"}))
        data = pd.concat(parts, ignore_index=True)
        options = recipe("linear-shared", **{"Curve points": 10_000, "Equation": "A+B*X+C*X^2", "Parameters": [
            {"name": "A", "start": 1., "shared": False, "fixed": False, "lower": None, "upper": None},
            {"name": "B", "start": 1., "shared": False, "fixed": False, "lower": None, "upper": None},
            {"name": "C", "start": .1, "shared": True, "fixed": False, "lower": None, "upper": None}]})
        with patch.object(engine, "_solve") as solve:
            with self.assertRaises(FieldError) as caught:
                engine.check_options(data, options)
            self.assertEqual(caught.exception.field, "Curve points")
            with self.assertRaises(FieldError):
                engine.global_custom_fit(data, options)
        solve.assert_not_called()
        options["Curve points"] = 2000
        engine.check_options(data, options)


class Artists(unittest.TestCase):
    def signature(self, result):
        return [(series.key, series.kind) for series in graph_series(result.figure.axes[0])]

    def test_collections_keep_series_identities_and_follow_the_line(self):
        plain = analyse(METHOD, frame("linear-shared"), RECIPES["linear-shared"])
        for drawing, kind in ((uncertainty.FILLED, PolyCollection), (uncertainty.LINES, LineCollection)):
            with self.subTest(drawing=drawing):
                result = run("linear-shared", **{"Band drawing": drawing})
                axes = result.figure.axes[0]
                self.assertEqual(self.signature(result), self.signature(plain))
                self.assertEqual(len(axes.get_legend().get_texts()), 2)
                bands = {c.get_gid(): c for c in axes.collections if str(c.get_gid()).startswith(uncertainty.GID)}
                self.assertEqual(set(bands), {"trama-global-band:A", "trama-global-band:B"})
                self.assertTrue(all(isinstance(c, kind) for c in bands.values()))
                lines = [s for s in graph_series(axes) if s.kind == "line"]
                # Same color on both fits must not confuse the link.
                apply_style(result.figure, {"series": {lines[0].key: {"color": "#9d2f75"},
                                                        lines[1].key: {"color": "#9d2f75"}}})
                apply_style(result.figure, {"series": {lines[1].key: {"color": "#112233"}}})
                color = lambda c: c.get_facecolor()[0, :3] if drawing == uncertainty.FILLED else c.get_colors()[0, :3]
                np.testing.assert_allclose(color(bands["trama-global-band:A"]), to_rgb(lines[0].artist.get_color()))
                np.testing.assert_allclose(color(bands["trama-global-band:B"]), to_rgb("#112233"))
                apply_style(result.figure, {"series": {lines[0].key: {"line_style": "none"}}})
                self.assertFalse(bands["trama-global-band:A"].get_visible())
                self.assertTrue(bands["trama-global-band:B"].get_visible())
                apply_style(result.figure, {})
                self.assertTrue(bands["trama-global-band:A"].get_visible())
                np.testing.assert_allclose(color(bands["trama-global-band:B"]), to_rgb(lines[1].artist.get_color()))

    def test_unicode_and_empty_labels(self):
        data = frame("linear-shared")
        data["Group"] = data["Group"].map({"A": "", "B": "Séries β, n°2"})
        result = analyse(METHOD, data, recipe("linear-shared"))
        gids = {c.get_gid() for c in result.figure.axes[0].collections if str(c.get_gid()).startswith(uncertainty.GID)}
        self.assertEqual(gids, {"trama-global-band:", "trama-global-band:Séries β, n°2"})


if __name__ == "__main__":
    unittest.main()
