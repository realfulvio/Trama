"""0.54 Fit spline/LOWESS: five interpolators, residuals, direct and inverse queries.

The fixtures and expected.json in data/spline_fit come from the package oracle (natural cubic from the second
derivative system, Akima from secants and Hermite pieces, a known truncated-power cubic for one knot, the
least-squares polynomial for zero knots and statsmodels LOWESS). The other tests check properties that need no
reference: limits, hidden fields, shifted and scaled X, tangents and shared ends.
"""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.nonparametric.smoothers_lowess import lowess

from analisi import spline_fit as sf
from analisi.processing import FieldError
from analisi.workbench import GROUPS, GRAPH_METHODS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "spline_fit"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = sf.SPLINE_FIT


def fixture(name):
    return pd.read_csv(DATA / f"{name}.csv")


def options(method, direction="None", segments=8, **extra):
    fields = {"X": "X", "Y": "Y", "Method": method, "Segments": segments, "Direction": direction}
    if direction != "None":
        fields["Query"] = "Query X" if direction == "Y from X" else "Query Y"
    return fields | extra


CASES = {
    "point-direct": ("linear-duplicates", options(sf.POINT, "Y from X", **{"Duplicate X": "Average", "Residuals": True})),
    "point-inverse": ("linear-duplicates", options(sf.POINT, "X from Y", **{"Duplicate X": "Average"})),
    "point-inverse-fine": ("linear-duplicates", options(sf.POINT, "X from Y", 1000, **{"Duplicate X": "Average"})),
    "natural-direct": ("natural", options(sf.CUBIC, "Y from X", Residuals=True)),
    "natural-inverse": ("natural", options(sf.CUBIC, "X from Y")),
    "akima-direct": ("akima", options(sf.AKIMA, "Y from X", Residuals=True)),
    "akima-inverse": ("akima", options(sf.AKIMA, "X from Y")),
    "fixed-knot-direct": ("smoothing", options(sf.SMOOTH, "Y from X", **{"Interior knots": 1, "Residuals": True})),
    "fixed-knot-inverse": ("smoothing", options(sf.SMOOTH, "X from Y", **{"Interior knots": 1})),
    "zero-knot": ("smoothing", options(sf.SMOOTH, "Y from X", **{"Interior knots": 0, "Residuals": True})),
    "lowess-plain": ("lowess", options(sf.LOWESS, "Y from X", **{"LOWESS fraction": .6, "Robust iterations": 0,
                                                               "Residuals": True})),
    "lowess-robust": ("lowess", options(sf.LOWESS, "Y from X", **{"LOWESS fraction": .6, "Robust iterations": 3,
                                                                "Residuals": True})),
    "lowess-inverse": ("lowess", options(sf.LOWESS, "X from Y", **{"LOWESS fraction": .6, "Robust iterations": 3})),
}


def cells(table):
    values = table.astype(object)
    return values.where(values.notna(), None).to_numpy().tolist()


def assert_cells(test, actual, expected):
    test.assertEqual(len(actual), len(expected))
    for row, wanted in zip(actual, expected, strict=True):
        test.assertEqual(len(row), len(wanted))
        for value, target in zip(row, wanted, strict=True):
            if isinstance(target, float):
                np.testing.assert_allclose(value, target, rtol=1e-9, atol=1e-9)
            else:
                test.assertEqual(value, target)


def statuses(result):
    return result.tables[sf.VALUES]["Status"].tolist()


def solve(frame, method, **extra):
    return analyse(METHOD, frame, {"X": "X", "Y": "Y", "Method": method, "Direction": "X from Y", "Query": "Q",
                                   **extra})


class ReferenceTables(unittest.TestCase):
    def test_package_fixtures(self):
        for name, (file, settings) in CASES.items():
            with self.subTest(name):
                expected = EXPECTED[name]
                result = analyse(METHOD, fixture(file), settings)
                sheets = [sheet for sheet in result.tables if sheet in expected["tables"]]
                self.assertEqual(sheets, list(expected["tables"]))
                self.assertEqual(set(result.tables), set(expected["tables"]))
                for sheet, values in expected["tables"].items():
                    table = result.tables[sheet]
                    if sheet == sf.COORDINATES:
                        self.assertEqual(len(table), expected["curve rows"])
                        table = table.iloc[expected["curve anchors"]]
                    assert_cells(self, cells(table), values)

    def test_segments_never_change_the_answers(self):
        frame = fixture("linear-duplicates")
        coarse, fine = (analyse(METHOD, frame, options(sf.POINT, "X from Y", segments, **{"Duplicate X": "Average"}))
                        for segments in (8, 1000))
        for sheet in (sf.VALUES, sf.SOLUTIONS, sf.PLATEAUS):
            pd.testing.assert_frame_equal(coarse.tables[sheet], fine.tables[sheet])
        for method in (sf.CUBIC, sf.AKIMA):
            coarse, fine = (analyse(METHOD, fixture("natural" if method == sf.CUBIC else "akima"),
                                    options(method, "X from Y", segments)) for segments in (8, 1000))
            pd.testing.assert_frame_equal(coarse.tables[sf.VALUES], fine.tables[sf.VALUES])

    def test_plateau_and_isolated_root(self):
        result = analyse(METHOD, fixture("linear-duplicates"), options(sf.POINT, "X from Y", **{"Duplicate X": "Average"}))
        values = result.tables[sf.VALUES]
        self.assertEqual(values.loc[values["Query"] == 3.0, "Status"].tolist(), [sf.AMBIGUOUS] * 2)
        plateaus = result.tables[sf.PLATEAUS]
        self.assertEqual(plateaus[["X lower", "X upper"]].to_numpy().tolist(), [[2.0, 3.0]] * 2)
        solutions = result.tables[sf.SOLUTIONS]
        self.assertIn(4.75, solutions["X"].tolist())
        self.assertNotIn(2.0, solutions["X"].tolist())
        self.assertNotIn(3.0, solutions["X"].tolist())

    def test_graph_draws_support_and_coordinates(self):
        result = analyse(METHOD, fixture("natural"), options(sf.CUBIC, "Y from X"))
        axis = result.figure.axes[0]
        coordinates = result.tables[sf.COORDINATES]
        line = next(line for line in axis.lines if len(line.get_xdata()) == len(coordinates))
        np.testing.assert_allclose(line.get_ydata(), coordinates["Y"])
        labels = [text.get_text() for text in axis.get_legend().get_texts()]
        self.assertEqual(labels[:2], ["Cubic spline", "Support points"] if labels[0] == "Cubic spline"
                         else ["Support points", "Cubic spline"])


class Limits(unittest.TestCase):
    def reject(self, frame, settings, field):
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, settings)
        self.assertEqual(raised.exception.field, field, str(raised.exception))
        return raised.exception

    def test_duplicates_rejected_then_averaged(self):
        frame = fixture("linear-duplicates")
        self.reject(frame, options(sf.POINT), "X")
        support = analyse(METHOD, frame, options(sf.POINT, **{"Duplicate X": "Average"})).tables[sf.SUPPORT]
        self.assertEqual(support.loc[support["X"] == 1, ["Y", "N"]].to_numpy().tolist(), [[2.0, 2]])

    def test_minimum_points_per_method(self):
        frame = pd.DataFrame({"X": np.arange(11.), "Y": np.sin(np.arange(11.))})
        for method, count in ((sf.POINT, 2), (sf.CUBIC, 4), (sf.AKIMA, 5), (sf.LOWESS, 12)):
            with self.subTest(method):
                self.reject(frame.iloc[:count - 1], options(method), "X")
                if count <= len(frame):
                    analyse(METHOD, frame.iloc[:count], options(method))

    def test_knots_without_support(self):
        unsupported = pd.DataFrame({"X": [0, .001, .002, .003, .004, 10], "Y": [1, 2, 1, 3, 2, 5]})
        self.reject(unsupported, options(sf.SMOOTH, **{"Interior knots": 2}), sf.KNOTS)
        frame = pd.DataFrame({"X": np.arange(6.), "Y": np.arange(6.) ** 2})
        self.reject(frame, options(sf.SMOOTH, **{"Interior knots": 3}), sf.KNOTS)
        analyse(METHOD, frame, options(sf.SMOOTH, **{"Interior knots": 2}))
        self.reject(frame, options(sf.SMOOTH, **{"Interior knots": 65}), sf.KNOTS)
        self.reject(frame, options(sf.SMOOTH, **{"Interior knots": -1}), sf.KNOTS)

    def test_zero_knots_is_the_cubic_polynomial(self):
        frame = fixture("smoothing")
        result = analyse(METHOD, frame, options(sf.SMOOTH, segments=50, **{"Interior knots": 0}))
        support = result.tables[sf.SUPPORT]
        cubic = np.polynomial.Polynomial.fit(support["X"], support["Y"], 3)
        coordinates = result.tables[sf.COORDINATES]
        np.testing.assert_allclose(coordinates["Y"], cubic(coordinates["X"]), rtol=1e-10, atol=1e-10)

    def test_segments_and_inverse_budget(self):
        frame = fixture("smoothing")
        self.reject(frame, options(sf.CUBIC, segments=10001), sf.SEGMENTS)
        self.reject(frame, options(sf.CUBIC, segments=1), sf.SEGMENTS)
        self.reject(frame, options(sf.CUBIC, segments=2.5), sf.SEGMENTS)
        large = pd.DataFrame({"X": np.arange(2100), "Y": np.arange(2100), "Query Y": np.arange(2100)})
        self.reject(large, options(sf.POINT, "X from Y"), sf.QUERY)
        # 952 queries × 2099 pieces = 1 998 248, inside the budget; Y from X has no inversion budget.
        inside = large.assign(**{"Query Y": np.r_[np.arange(952.), [np.nan] * 1148]})
        self.assertEqual(len(analyse(METHOD, inside, options(sf.POINT, "X from Y")).tables[sf.VALUES]), 952)
        analyse(METHOD, large.rename(columns={"Query Y": "Query X"}), options(sf.POINT, "Y from X"))
        # LOWESS draws max(Segments, 4n): 2501 points need 10 004 segments.
        many = pd.DataFrame({"X": np.arange(2501.), "Y": np.sin(np.arange(2501.))})
        self.reject(many, options(sf.LOWESS), "X")

    def test_lowess_fraction_and_iterations(self):
        frame = fixture("lowess")
        self.reject(frame, options(sf.LOWESS, **{"LOWESS fraction": .15}), sf.FRACTION)
        analyse(METHOD, frame, options(sf.LOWESS, **{"LOWESS fraction": .25}))  # floor(.25 × 12) = 3
        for bad in (0, 1.01, "bad", float("nan")):
            self.reject(frame, options(sf.LOWESS, **{"LOWESS fraction": bad}), sf.FRACTION)
        for bad in (-1, 4, 1.5, "bad"):
            self.reject(frame, options(sf.LOWESS, **{"Robust iterations": bad}), sf.ITERATIONS)
        for iterations in range(4):
            result = analyse(METHOD, frame, options(sf.LOWESS, **{"LOWESS fraction": .6, "Residuals": True,
                                                                  "Robust iterations": iterations}))
            support = result.tables[sf.SUPPORT]
            smooth = lowess(support["Y"], support["X"], frac=.6, it=iterations, is_sorted=True, return_sorted=False)
            fitted = result.tables[sf.RESIDUAL_SHEET].sort_values("X")["Fitted Y"]
            np.testing.assert_allclose(fitted, smooth, rtol=1e-9, atol=1e-9)
            self.assertEqual(len(result.tables[sf.COORDINATES]), 4 * len(support) + 1)

    def test_hidden_fields_are_ignored(self):
        frame = fixture("natural")
        plain = analyse(METHOD, frame, options(sf.CUBIC))
        hidden = analyse(METHOD, frame, options(sf.CUBIC) | {"LOWESS fraction": "bad", "Robust iterations": 9,
                                                            "Interior knots": -1, "Query": "missing"})
        for name, table in plain.tables.items():
            pd.testing.assert_frame_equal(hidden.tables[name], table)
        self.assertEqual(sf.visibility(sf.CUBIC, "None"),
                         {sf.KNOTS: False, sf.FRACTION: False, sf.ITERATIONS: False, sf.QUERY: False})
        self.assertEqual(sf.visibility(sf.LOWESS, "X from Y"),
                         {sf.KNOTS: False, sf.FRACTION: True, sf.ITERATIONS: True, sf.QUERY: True})

    def test_query_field_errors(self):
        frame = fixture("linear-duplicates")
        settings = options(sf.POINT, "Y from X", **{"Duplicate X": "Average"})
        self.reject(frame, settings | {"Query": None}, sf.QUERY)
        self.reject(frame, settings | {"Query": "X"}, sf.QUERY)
        text = frame.astype({"Query X": object})
        text.at[1, "Query X"] = "bad"
        self.reject(text, settings, sf.QUERY)
        infinite = frame.assign(X=frame["X"].astype(float))
        infinite.at[0, "X"] = np.inf
        self.reject(infinite, settings, "X")
        self.reject(frame, settings | {"Y": "X"}, "Y")

    def test_excluded_and_empty_queries_are_skipped(self):
        frame = fixture("linear-duplicates")
        frame.loc[[0, 3], "Query X"] = np.nan
        result = analyse(METHOD, frame, options(sf.POINT, "Y from X", **{"Duplicate X": "Average"}))
        self.assertEqual(result.tables[sf.VALUES]["Source row"].tolist(), [1, 2, 4, 5, 6, 8])
        self.assertEqual(result.tables[sf.VALUES].index.tolist(), [1, 2, 4, 5, 6, 8])


class Inversion(unittest.TestCase):
    def test_precision_of_shifted_and_scaled_x(self):
        base = np.array([0., 1, 2, 3, 4])
        for shift, scale in ((0, 1), (1e6, 1), (0, 2. ** -40), (-4096, 2. ** -10), (2. ** 40, 2. ** -8)):
            with self.subTest(shift=shift, scale=scale):
                x = shift + scale * base
                # Exactly representable X: the natural cubic stays symmetric about the middle node.
                self.assertTrue(np.allclose(np.diff(x), scale, rtol=0, atol=0))
                frame = pd.DataFrame({"X": x, "Y": [4., 1, 0, 1, 4], "Q": [1, 0, 4, 5, np.nan]})
                for method in (sf.POINT, sf.CUBIC):
                    result = solve(frame, method)
                    self.assertEqual(statuses(result), [sf.AMBIGUOUS, sf.IN_RANGE, sf.AMBIGUOUS, sf.OUTSIDE])
                    self.assertEqual(result.tables[sf.VALUES].at[1, "Value"], x[2])
                    self.assertEqual(result.tables[sf.SOLUTIONS]["X"].tolist(), [x[1], x[3], x[0], x[4]])

    def test_direct_values_are_affine_invariant(self):
        frame = fixture("akima")
        reference = analyse(METHOD, frame, options(sf.AKIMA, "Y from X")).tables[sf.VALUES]
        moved = frame.assign(**{"X": 1e5 + 1e-3 * frame["X"], "Query X": 1e5 + 1e-3 * frame["Query X"]})
        shifted = analyse(METHOD, moved, options(sf.AKIMA, "Y from X")).tables[sf.VALUES]
        np.testing.assert_allclose(shifted["Value"].astype(float), reference["Value"].astype(float), rtol=1e-7)

    def test_interior_tangent(self):
        x = np.arange(6.)
        frame = pd.DataFrame({"X": x, "Y": (x - 2.5) ** 2, "Q": [0., 1e-3, -1e-3, np.nan, np.nan, np.nan]})
        result = solve(frame, sf.SMOOTH, **{"Interior knots": 0})
        self.assertEqual(statuses(result), [sf.IN_RANGE, sf.AMBIGUOUS, sf.OUTSIDE])
        self.assertAlmostEqual(result.tables[sf.VALUES].at[0, "Value"], 2.5, places=6)
        np.testing.assert_allclose(result.tables[sf.SOLUTIONS]["X"], [2.5 - 1e-3 ** .5, 2.5 + 1e-3 ** .5], rtol=1e-9)

    def test_shared_junction_is_one_solution(self):
        # Monotone through the node X=2 where two pieces meet: one root, never two.
        x = np.arange(6.)
        frame = pd.DataFrame({"X": x, "Y": x ** 3, "Q": [8., 27, 125, np.nan, np.nan, np.nan]})
        for method in (sf.POINT, sf.CUBIC, sf.AKIMA):
            with self.subTest(method):
                result = solve(frame, method)
                self.assertEqual(statuses(result), [sf.IN_RANGE] * 3)
                self.assertEqual(result.tables[sf.VALUES]["Value"].tolist(), [2.0, 3.0, 5.0])
                self.assertNotIn(sf.SOLUTIONS, result.tables)
        knots = solve(frame, sf.SMOOTH, **{"Interior knots": 1})  # x³ is exact, the knot sits at 2.5
        self.assertEqual(statuses(knots), [sf.IN_RANGE] * 3)
        np.testing.assert_allclose(knots.tables[sf.VALUES]["Value"].astype(float), [2, 3, 5], atol=1e-9)

    def test_flat_cubic_plateau(self):
        frame = pd.DataFrame({"X": np.arange(6.), "Y": [2.] * 6, "Q": [2., 3, np.nan, np.nan, np.nan, np.nan]})
        result = solve(frame, sf.AKIMA)
        self.assertEqual(statuses(result), [sf.AMBIGUOUS, sf.OUTSIDE])
        self.assertEqual(result.tables[sf.PLATEAUS][["X lower", "X upper"]].to_numpy().tolist(), [[0.0, 5.0]])
        self.assertNotIn(sf.SOLUTIONS, result.tables)

    def test_unrepresentable_values_are_readable(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 3], "Y": [0., 1e308, -1e308, 1e308]})
        with self.assertRaises(ValueError) as raised:
            analyse(METHOD, frame, options(sf.CUBIC, Residuals=True))
        self.assertIn("representable", str(raised.exception))


class Integration(unittest.TestCase):
    def test_menu_and_legacy_smoothing(self):
        self.assertIn(METHOD, GROUPS["Regression and Curves"])
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(METHODS[METHOD], sf.OPTIONS)
        self.assertEqual(list(sf.OPTIONS)[:3], ["X", "Y", "Method"])
        frame = fixture("lowess")
        result = analyse("Smooth / differentiate / integrate", frame,
                         {"X": "X", "Y": "Y", "Method": "LOWESS", "LOWESS fraction": .6})
        self.assertEqual(list(result.tables), ["Curve"])
        self.assertEqual(list(result.tables["Curve"].columns), ["X", "Original Y", "LOWESS"])

    def test_row_title_is_optional(self):
        frame = fixture("natural").drop(columns="Row title")
        result = analyse(METHOD, frame, options(sf.CUBIC, "Y from X", Residuals=True))
        self.assertEqual(list(result.tables[sf.VALUES].columns), ["Source row", "Query", "Value", "Status"])
        self.assertEqual(list(result.tables[sf.RESIDUAL_SHEET].columns),
                         ["Source row", "X", "Observed Y", "Fitted Y", "Residual"])


if __name__ == "__main__":
    unittest.main()
