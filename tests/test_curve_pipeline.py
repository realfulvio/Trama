"""0.93 Curve pipeline: differences, cumulative trapezoid and Savitzky–Golay smoothing on XY curves.

The fixtures and expected.json in data/curve_pipeline are synthetic oracles worked out by hand and checked with an
independent rational calculation (x² + 2x + 3 for the differences, the weights (-3, 12, 17, 12, -3) / 35 for the
smoothing). The remaining tests check properties that need no reference: affine X and Y rescaling, gaps and blocks,
source rows, limits, hidden fields, exact rational Savitzky–Golay weights, non-finite values and the 50,000 row size.
"""
from fractions import Fraction
import json
from pathlib import Path
import time
import tracemalloc
import unittest

import numpy as np
import pandas as pd

from analisi import curve_pipeline as cp
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "curve_pipeline"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = cp.CURVE_METHOD
COLUMNS = ["X", "Value", "Block", "First source row", "Last source row"]


def fixture(name):
    return pd.read_csv(DATA / f"{name}.csv")


def uniform():
    """The even grid with its clean parabola in column Y (the fixture also has the Impulse copy)."""
    return fixture("uniform").assign(Y=lambda frame: frame["Clean"])


def options(**extra):
    return {"X": "X", "Y": "Y", "Method": cp.PIPELINE, **extra}


def run(frame, **extra):
    return analyse(METHOD, frame, options(**extra))


def curve(frame, **extra):
    return run(frame, **extra).tables["Curve"]


def settings(result):
    table = result.tables["Settings"]
    return dict(zip(table["Setting"], table["Value"]))


def rows(table):
    return table.to_numpy(dtype=float).tolist()


def failure(frame, field, **extra):
    """The message of the FieldError that a run raises on ``field``."""
    try:
        run(frame, **extra)
    except FieldError as error:
        assert error.field == field, (error.field, str(error))
        return str(error)
    raise AssertionError(f"Expected a field error on {field}")


class Oracles(unittest.TestCase):
    def check(self, name, frame, **extra):
        table = curve(frame, **extra)
        self.assertEqual(list(table), COLUMNS)
        target = np.asarray(EXPECTED[name])
        np.testing.assert_allclose(table[["X", "Value"]].to_numpy(dtype=float), target[:, :2], rtol=1e-11, atol=1e-11)
        np.testing.assert_array_equal(table[COLUMNS[2:]].to_numpy(), target[:, 2:])

    def test_first_difference_of_an_unsorted_sheet(self):
        self.check("first", fixture("irregular"), Operation=cp.FIRST)

    def test_second_difference_is_constant_for_a_parabola(self):
        self.check("second", fixture("irregular"), Operation=cp.SECOND)

    def test_cumulative_trapezoid_with_baseline_and_initial_value(self):
        table = curve(fixture("irregular"), Operation=cp.CUMULATIVE, Baseline=3, **{"Initial integral": 2})
        np.testing.assert_allclose(table["Value"].iloc[-1], 452, rtol=0, atol=1e-11)
        self.check("integral", fixture("irregular"), Operation=cp.CUMULATIVE, Baseline=3, **{"Initial integral": 2})

    def test_smoothing_a_series_with_an_impulse(self):
        self.check("sg", fixture("uniform"), Y="Impulse", Smoothing=cp.SAVITZKY_GOLAY)

    def test_difference_then_smoothing_uses_the_midpoints(self):
        self.check("pipeline", fixture("uniform"), Y="Clean", Operation=cp.FIRST, Smoothing=cp.SAVITZKY_GOLAY)

    def test_a_missing_y_splits_the_curve(self):
        self.check("gaps", fixture("gaps"), Operation=cp.FIRST)

    def test_identity_returns_the_samples_in_x_order(self):
        table = curve(fixture("irregular"))
        self.assertEqual(table["X"].tolist(), [0, 1, 3, 6, 10])
        self.assertEqual(table["Value"].tolist(), [3, 6, 18, 51, 123])
        self.assertEqual(table["First source row"].tolist(), table["Last source row"].tolist())
        self.assertEqual(table["First source row"].tolist(), [1, 3, 0, 4, 2])


class Weights(unittest.TestCase):
    @staticmethod
    def exact(m, degree, values):
        """The constant term of the least-squares polynomial, from the normal equations in rational arithmetic."""
        offsets = range(-m, m + 1)
        size = degree + 1
        normal = [[Fraction(sum(Fraction(j) ** (r + c) for j in offsets)) for c in range(size)] for r in range(size)]
        right = [Fraction(sum(Fraction(j) ** r * value for j, value in zip(offsets, values))) for r in range(size)]
        for column in range(size):
            pivot = next(r for r in range(column, size) if normal[r][column] != 0)
            normal[column], normal[pivot] = normal[pivot], normal[column]
            right[column], right[pivot] = right[pivot], right[column]
            for r in range(size):
                if r != column and normal[r][column] != 0:
                    factor = normal[r][column] / normal[column][column]
                    normal[r] = [a - factor * b for a, b in zip(normal[r], normal[column])]
                    right[r] -= factor * right[column]
        return right[0] / normal[0][0]

    def test_five_point_quadratic_weights(self):
        weights = cp.savitzky_golay_weights(2, 2)
        np.testing.assert_allclose(weights, np.array([-3, 12, 17, 12, -3]) / 35, rtol=0, atol=1e-14)
        self.assertAlmostEqual(weights.sum(), 1, places=14)
        self.assertFalse(weights.flags.writeable)

    def test_every_half_window_and_degree_matches_exact_arithmetic(self):
        rng = np.random.default_rng(11)
        for m in (1, 2, 3, 5, 9):
            for degree in range(0, min(6, 2 * m) + 1):
                values = rng.integers(-40, 40, size=2 * m + 1)
                weights = cp.savitzky_golay_weights(m, degree)
                wanted = self.exact(m, degree, [Fraction(int(v)) for v in values])
                self.assertAlmostEqual(float(weights @ values), float(wanted), delta=1e-11 * (1 + abs(float(wanted))),
                                       msg=(m, degree))

    def test_weights_are_symmetric_and_reproduce_a_polynomial(self):
        for m, degree in ((3, 3), (6, 4), (50, 6)):
            weights = cp.savitzky_golay_weights(m, degree)
            np.testing.assert_allclose(weights, weights[::-1], rtol=0, atol=1e-12)
            offsets = np.arange(-m, m + 1) / m
            for power in range(degree + 1):
                self.assertAlmostEqual(float(weights @ offsets ** power), 1.0 if power == 0 else 0.0, delta=1e-9)

    def test_smoothing_leaves_a_cubic_untouched_by_a_cubic_filter(self):
        x = np.arange(0, 30) * .5
        frame = pd.DataFrame({"X": x, "Y": 2 * x ** 3 - x ** 2 + 5})
        table = curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 4, "Polynomial degree": 3})
        np.testing.assert_allclose(table["Value"], (2 * x ** 3 - x ** 2 + 5)[4:-4], rtol=1e-11)
        self.assertEqual(len(table), 30 - 8)


class Rescaling(unittest.TestCase):
    """Rates and cumulative values carry the units of X and Y: a shifted and rescaled sheet changes them predictably."""

    def setUp(self):
        x = np.array([0., 1, 2.5, 3, 5, 6.5, 8])
        self.base = pd.DataFrame({"X": x, "Y": x ** 2 - 3 * x + 4})
        self.shift, self.stretch, self.gain = 100.0, 4.0, 10.0
        scaled = self.shift + self.stretch * self.base["X"]
        self.scaled = pd.DataFrame({"X": scaled, "Y": self.gain * self.base["Y"]})

    def test_rate_scales_with_gain_over_stretch(self):
        for operation, power in ((cp.FIRST, 1), (cp.SECOND, 2)):
            before, after = curve(self.base, Operation=operation), curve(self.scaled, Operation=operation)
            np.testing.assert_allclose(after["Value"], before["Value"] * self.gain / self.stretch ** power, rtol=1e-10)
            np.testing.assert_allclose(after["X"], self.shift + self.stretch * before["X"], rtol=1e-12)

    def test_cumulative_value_scales_with_gain_times_stretch(self):
        before = curve(self.base, Operation=cp.CUMULATIVE, Baseline=2, **{"Initial integral": 1})
        after = curve(self.scaled, Operation=cp.CUMULATIVE, Baseline=2 * self.gain,
                      **{"Initial integral": self.gain * self.stretch})
        np.testing.assert_allclose(after["Value"], self.gain * self.stretch * before["Value"], rtol=1e-10)

    def test_descending_stretch_gives_negative_rates_and_signed_area(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 3], "Y": [4., 3, 1, 0]})
        self.assertEqual(curve(frame, Operation=cp.FIRST)["Value"].tolist(), [-1, -2, -1])
        self.assertEqual(curve(frame, Operation=cp.CUMULATIVE)["Value"].tolist(), [0, 3.5, 5.5, 6.0])
        # Below the baseline the area counts negatively.
        self.assertLess(curve(frame, Operation=cp.CUMULATIVE, Baseline=10)["Value"].iloc[-1], 0)


class Blocks(unittest.TestCase):
    def test_a_lone_sample_keeps_the_initial_value_and_every_block_restarts(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4, 5, 6], "Y": [1, 2, None, 5, None, 7, 8]})
        table = curve(frame, Operation=cp.CUMULATIVE, **{"Initial integral": 10})
        self.assertEqual(table["Block"].tolist(), [1, 1, 2, 3, 3])
        self.assertEqual(table["Value"].tolist(), [10, 11.5, 10, 10, 17.5])
        self.assertEqual(table["First source row"].tolist(), [0, 0, 3, 5, 5])
        self.assertEqual(table["Last source row"].tolist(), [0, 1, 3, 5, 6])

    def test_blocks_keep_their_number_when_one_block_has_no_output(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4, 5], "Y": [3, None, 1, 2, None, 5]})
        result = run(frame, Operation=cp.FIRST)
        self.assertEqual(result.tables["Curve"]["Block"].tolist(), [2])
        self.assertEqual(result.tables["Curve"]["Value"].tolist(), [1])
        info = settings(result)
        self.assertEqual((info["Blocks"], info["Blocks without output"], info["Output points"]), (3, 2, 1))

    def test_second_difference_needs_three_points_in_a_block(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4, 5, 6], "Y": [0, 1, 4, None, 7, 11, 16]})
        table = curve(frame, Operation=cp.SECOND)
        self.assertEqual(table["Block"].tolist(), [1, 2])
        self.assertEqual(table["Value"].tolist(), [2, 1])
        self.assertEqual(table["X"].tolist(), [1.0, 5.0])

    def test_nothing_to_difference_is_an_error_of_the_operation(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3], "Y": [1, None, 3, None]})
        self.assertIn("No block", failure(frame, "Operation", Operation=cp.FIRST))
        self.assertEqual(curve(frame, Operation=cp.IDENTITY)["Block"].tolist(), [1, 2])

    def test_a_missing_or_excluded_x_has_no_place_and_a_missing_y_is_a_gap(self):
        frame = pd.DataFrame({"X": [0, 1, np.nan, 3, 4, 5], "Y": [1, 2, 9, np.nan, 5, 6]})
        result = run(frame, Operation=cp.FIRST)
        info = settings(result)
        self.assertEqual((info["Valid points"], info["Rows skipped (X missing or excluded)"],
                          info["Gap rows (Y missing or excluded)"], info["Blocks"]), (4, 1, 1, 2))
        self.assertEqual(result.tables["Curve"]["X"].tolist(), [.5, 4.5])
        self.assertEqual(result.tables["Curve"]["First source row"].tolist(), [0, 4])

    def test_duplicate_x_is_an_error_of_x_even_when_one_y_is_empty(self):
        frame = pd.DataFrame({"X": [0, 1, 1, 2], "Y": [2, 3, np.nan, 5]})
        self.assertIn("1", failure(frame, "X"))
        failure(pd.DataFrame({"X": [0, 1, 1, 2], "Y": [2, 3, 4, 5]}), "X", Operation=cp.FIRST)

    def test_source_rows_are_positions_whatever_the_index(self):
        frame = fixture("irregular")
        reference = curve(frame, Operation=cp.FIRST)
        for index in ([f"row-{i + 101}" for i in range(5)], [40, 3, 99, 12, 7], pd.MultiIndex.from_tuples(
                [("a", 1), ("a", 2), ("b", 1), ("b", 2), ("c", 1)])):
            shifted = frame.copy()
            shifted.index = index
            pd.testing.assert_frame_equal(curve(shifted, Operation=cp.FIRST), reference)

    def test_mixed_column_types_and_empty_text_cells(self):
        frame = pd.DataFrame({"Name": list("abcde"), "X": ["0", "1", "", " ", "4"], "Y": [1.0, 2.0, 3.0, 4.0, "7"]})
        table = curve(frame, Operation=cp.FIRST)
        self.assertEqual(table["Value"].tolist(), [1.0, 5 / 3])
        self.assertEqual(table["First source row"].tolist(), [0, 1])

    def test_a_row_at_the_bottom_with_a_small_x_gives_decreasing_source_rows(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 0], "Y": [5, 6, 8, 4]})
        table = curve(frame, Operation=cp.FIRST)
        self.assertEqual(table["First source row"].tolist(), [3, 0, 1])
        self.assertEqual(table["Last source row"].tolist(), [0, 1, 2])
        self.assertEqual(curve(frame, Operation=cp.CUMULATIVE)["First source row"].tolist(), [3, 3, 3, 3])
        self.assertEqual(curve(frame, Operation=cp.CUMULATIVE)["Last source row"].tolist(), [3, 0, 1, 2])


class Smoothing(unittest.TestCase):
    def test_a_short_irregular_block_does_not_contribute_and_does_not_block(self):
        # Block 1 has 3 points on an irregular grid, block 2 has 7 points on an even one.
        frame = pd.DataFrame({"X": [0, 1, 7, 9] + [10 + i for i in range(7)],
                              "Y": [1, 2, 4, None] + [float(i * i) for i in range(7)]})
        result = run(frame, Smoothing=cp.SAVITZKY_GOLAY)
        table = result.tables["Curve"]
        self.assertEqual(table["Block"].tolist(), [2, 2, 2])
        self.assertEqual(table["X"].tolist(), [12, 13, 14])
        np.testing.assert_allclose(table["Value"], [4, 9, 16], rtol=1e-12, atol=1e-12)
        self.assertEqual(settings(result)["Blocks without output"], 1)
        self.assertEqual(table["First source row"].tolist(), [4, 5, 6])
        self.assertEqual(table["Last source row"].tolist(), [8, 9, 10])

    def test_an_eligible_irregular_block_is_an_error_of_smoothing(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4.5, 6, 7], "Y": [1., 2, 3, 4, 5, 6, 7]})
        self.assertIn("evenly spaced", failure(frame, "Smoothing", Smoothing=cp.SAVITZKY_GOLAY))
        # Without smoothing the same sheet has a second difference.
        self.assertEqual(len(curve(frame, Operation=cp.SECOND)), 5)

    def test_the_grid_tolerance_is_relative_to_the_median_step(self):
        x = np.arange(6, dtype=float)
        within = pd.DataFrame({"X": x + np.array([0, 0, 0, 0, 0, 5e-11]), "Y": x * 2})
        self.assertEqual(len(curve(within, Smoothing=cp.SAVITZKY_GOLAY)), 2)
        outside = pd.DataFrame({"X": x + np.array([0, 0, 0, 0, 0, 5e-9]), "Y": x * 2})
        failure(outside, "Smoothing", Smoothing=cp.SAVITZKY_GOLAY)

    def test_no_block_with_a_full_window_is_an_error_of_the_half_window(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3], "Y": [1., 2, 3, 4]})
        self.assertIn("5 points", failure(frame, "Half-window", Smoothing=cp.SAVITZKY_GOLAY))
        self.assertEqual(len(curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 1})), 2)

    def test_the_operation_output_decides_whether_a_window_fits(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4], "Y": [1., 2, 4, 7, 11]})
        self.assertEqual(len(curve(frame, Smoothing=cp.SAVITZKY_GOLAY)), 1)
        # Four first differences cannot fill a window of five points.
        failure(frame, "Half-window", Operation=cp.FIRST, Smoothing=cp.SAVITZKY_GOLAY)

    def test_smoothing_a_cumulative_integral_extends_the_source_rows(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4, 5], "Y": [1., 1, 1, 1, 1, 1]})
        table = curve(frame, Operation=cp.CUMULATIVE, Smoothing=cp.SAVITZKY_GOLAY)
        np.testing.assert_allclose(table["Value"], [2, 3], rtol=1e-12)
        self.assertEqual(table["First source row"].tolist(), [0, 0])
        self.assertEqual(table["Last source row"].tolist(), [4, 5])

    def test_a_constant_series_stays_constant(self):
        frame = pd.DataFrame({"X": np.arange(20) * .25, "Y": np.full(20, 3.5)})
        for m in (1, 7, 9):
            np.testing.assert_allclose(curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": m,
                                                                                   "Polynomial degree": 0})["Value"],
                                       3.5, rtol=1e-13)

    def test_a_noisy_curve_is_smoother_than_its_input(self):
        rng = np.random.default_rng(3)
        x = np.linspace(0, 1, 200)
        frame = pd.DataFrame({"X": x, "Y": np.sin(6 * x) + rng.normal(0, .2, x.size)})
        smoothed = curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 10, "Polynomial degree": 2})["Value"]
        self.assertLess(np.abs(np.diff(smoothed.to_numpy(), 2)).mean(), .1 * np.abs(np.diff(frame["Y"].to_numpy(), 2)).mean())


class Validation(unittest.TestCase):
    def test_a_degree_above_the_window_rule_names_the_degree(self):
        frame = uniform()
        self.assertIn("0 to 4", failure(frame, "Polynomial degree", Smoothing=cp.SAVITZKY_GOLAY, **{"Polynomial degree": 5}))
        self.assertEqual(len(curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Polynomial degree": 4})), 5)
        # A half-window of three allows degree six; seven is too much.
        failure(frame, "Polynomial degree", Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 3, "Polynomial degree": 7})
        curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 3, "Polynomial degree": 6})

    def test_half_window_limits_and_types(self):
        frame = uniform()
        for bad in (0, 51, -1, 2.5, "x", True, None, float("nan")):
            failure(frame, "Half-window", Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": bad})
        for good in (1, "2", 2.0):
            curve(frame, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": good, "Polynomial degree": 1})

    def test_numbers_accept_a_decimal_comma_and_reject_everything_else(self):
        frame = fixture("irregular")
        comma = curve(frame, Operation=cp.CUMULATIVE, Baseline="3,0", **{"Initial integral": "2,5"})
        self.assertEqual(comma["Value"].iloc[0], 2.5)
        for field in ("Baseline", "Initial integral"):
            for bad in (float("inf"), float("nan"), "abc", None, True, [1]):
                failure(frame, field, Operation=cp.CUMULATIVE, **{field: bad})

    def test_fields_that_do_not_act_are_not_checked(self):
        frame = fixture("irregular")
        reference = curve(frame, Operation=cp.FIRST)
        pd.testing.assert_frame_equal(curve(frame, Operation=cp.FIRST, Baseline="abc", **{
            "Initial integral": float("inf"), "Half-window": 999, "Polynomial degree": -3}), reference)
        # Smoothing off ignores the window even for the integral.
        curve(frame, Operation=cp.CUMULATIVE, **{"Half-window": 999})

    def test_choices_columns_and_defaults(self):
        frame = fixture("irregular")
        failure(frame, "Operation", Operation="Third difference")
        failure(frame, "Smoothing", Smoothing="Gaussian")
        failure(frame, "X", X="Missing")
        failure(frame, "Y", Y="X")
        failure(frame, "Y", Y=None)
        defaults = curve(frame)
        self.assertEqual(defaults["Value"].tolist(), [3, 6, 18, 51, 123])
        self.assertEqual(cp.OPTIONS[cp.OPERATION][0], "Identity")
        self.assertEqual(cp.OPTIONS[cp.SMOOTHING][0], "None")
        self.assertEqual((cp.OPTIONS[cp.BASELINE], cp.OPTIONS[cp.INITIAL], cp.OPTIONS[cp.HALF_WINDOW],
                          cp.OPTIONS[cp.DEGREE]), (0, 0, 2, 2))

    def test_text_and_infinite_values_are_errors_of_their_own_field(self):
        message = failure(pd.DataFrame({"X": [0, 1, "two", 3], "Y": [1, 2, 3, 4]}), "X")
        self.assertIn("row 3", message)
        self.assertIn("row 2", failure(pd.DataFrame({"X": [0, 1, 2, 3], "Y": [1, "n/a", 3, 4]}), "Y"))
        self.assertIn("infinite", failure(pd.DataFrame({"X": [0, 1, np.inf, 3], "Y": [1, 2, 3, 4]}), "X"))
        self.assertIn("infinite", failure(pd.DataFrame({"X": [0, 1, 2, 3], "Y": [1, -np.inf, 3, 4]}), "Y"))
        failure(pd.DataFrame({"X": [0, 1, 2, 3], "Y": ["1", "inf", "3", "4"]}), "Y")
        failure(pd.DataFrame({"X": [0, 1, 2, 3], "Y": [1, 2, 3, "nan"]}), "Y")
        failure(pd.DataFrame({"X": [0.0, 1, 2], "Y": [None, None, None]}), "Y")
        failure(pd.DataFrame({"X": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]), "Y": [1, 2, 3]}), "X")

    def test_values_the_calculation_cannot_represent_are_reported_not_hidden(self):
        huge = pd.DataFrame({"X": [0., 1, 2, 3, 4, 5], "Y": [1e308, -1e308, 1e308, -1e308, 1e308, -1e308]})
        self.assertIn("not finite", failure(huge, "Operation", Operation=cp.FIRST))
        failure(huge, "Operation", Operation=cp.CUMULATIVE, Baseline=-1e308)
        # Weights (-3, 12, 17, 12, -3) / 35 on a window that follows their signs add up to 47 / 35 of the largest value.
        peak = pd.DataFrame({"X": [0., 1, 2, 3, 4], "Y": [-1.7e308, 1.7e308, 1.7e308, 1.7e308, -1.7e308]})
        failure(peak, "Smoothing", Smoothing=cp.SAVITZKY_GOLAY)
        tiny = pd.DataFrame({"X": [0., 5e-324, 1e-323], "Y": [0., 1e300, 2e300]})
        failure(tiny, "Operation", Operation=cp.FIRST)

    def test_the_row_limit_is_checked_before_anything_is_converted(self):
        big = pd.DataFrame({"X": np.zeros(cp.MAX_ROWS + 1), "Y": np.zeros(cp.MAX_ROWS + 1)})
        self.assertIn("200,000", failure(big, "X"))
        edge = pd.DataFrame({"X": np.arange(cp.MAX_ROWS, dtype=float), "Y": np.ones(cp.MAX_ROWS)})
        self.assertEqual(len(curve(edge)), cp.MAX_ROWS)


class Dispatcher(unittest.TestCase):
    def test_the_older_choices_keep_their_sheet_columns_numbers_and_fields(self):
        frame = fixture("irregular")
        frame.index = [f"row-{i + 101}" for i in range(len(frame))]
        old = {"X": "X", "Y": "Y", "LOWESS fraction": .5}
        result = analyse(METHOD, frame, {**old, "Method": "Differentiate"})
        self.assertEqual(list(result.tables), ["Curve"])
        self.assertEqual(list(result.tables["Curve"]), ["X", "Original Y", "Differentiate"])
        self.assertEqual(result.tables["Curve"].index.tolist(), ["row-102", "row-104", "row-101", "row-105", "row-103"])
        np.testing.assert_allclose(result.tables["Curve"]["Differentiate"], [2, 4, 8, 14, 22], rtol=0, atol=1e-12)
        cumulative = analyse(METHOD, frame, {**old, "Method": "Cumulative integral"})
        self.assertEqual(list(cumulative.tables["Curve"]), ["X", "Original Y", "Cumulative integral"])
        lowess = analyse(METHOD, fixture("uniform").assign(Y=lambda f: f["Clean"]), {**old, "Method": "LOWESS"})
        self.assertEqual(list(lowess.tables["Curve"]), ["X", "Original Y", "LOWESS"])
        # The pipeline keys are ignored by the older choices.
        extra = analyse(METHOD, frame, {**old, "Method": "Differentiate", "Operation": "Nonsense", "Half-window": 0})
        pd.testing.assert_frame_equal(extra.tables["Curve"], result.tables["Curve"])

    def test_the_method_choices_keep_lowess_first_and_the_pipeline_last(self):
        spec = METHODS[METHOD]
        self.assertEqual(spec["Method"], ("LOWESS", "Differentiate", "Cumulative integral", "Curve pipeline"))
        self.assertEqual(list(spec)[:4], ["X", "Y", "Method", "LOWESS fraction"])
        self.assertEqual(list(spec)[4:], list(cp.PIPELINE_FIELDS))
        self.assertIn(METHOD, GROUPS["Data Exploration and Summary"])
        self.assertIn(METHOD, GRAPH_METHODS)

    def test_visibility_follows_the_method_the_operation_and_the_smoothing(self):
        shown = lambda *state: {name for name, visible in cp.visibility(*state).items() if visible}
        self.assertEqual(shown("LOWESS", cp.IDENTITY, cp.NO_SMOOTHING), {"LOWESS fraction"})
        self.assertEqual(shown("Differentiate", cp.CUMULATIVE, cp.SAVITZKY_GOLAY), {"LOWESS fraction"})
        self.assertEqual(shown(cp.PIPELINE, cp.IDENTITY, cp.NO_SMOOTHING), {cp.OPERATION, cp.SMOOTHING})
        self.assertEqual(shown(cp.PIPELINE, cp.CUMULATIVE, cp.NO_SMOOTHING),
                         {cp.OPERATION, cp.SMOOTHING, cp.BASELINE, cp.INITIAL})
        self.assertEqual(shown(cp.PIPELINE, cp.FIRST, cp.SAVITZKY_GOLAY),
                         {cp.OPERATION, cp.SMOOTHING, cp.HALF_WINDOW, cp.DEGREE})


class Results(unittest.TestCase):
    def test_the_sheets_and_their_columns(self):
        result = run(fixture("irregular"), Operation=cp.CUMULATIVE, Baseline=3, **{"Initial integral": 2})
        self.assertEqual(list(result.tables), ["Curve", "Settings"])
        table, info = result.tables["Curve"], result.tables["Settings"]
        self.assertEqual(list(info), ["Setting", "Value"])
        self.assertEqual(table["Block"].dtype, np.int64)
        self.assertEqual(table["First source row"].dtype, np.int64)
        values = settings(result)
        self.assertEqual(values["Operation"], "Cumulative trapezoid")
        self.assertEqual((values["Baseline"], values["Initial integral"]), (3, 2))
        self.assertEqual((values["Valid points"], values["Blocks"], values["Output points"]), (5, 1, 5))
        self.assertNotIn("Half-window", values)
        self.assertNotIn("Note", values)
        self.assertIsInstance(values["Valid points"], int)
        csv = table.to_csv(index=False)
        self.assertTrue(csv.startswith("X,Value,Block,First source row,Last source row"))

    def test_the_settings_of_a_smoothed_run_carry_the_window_and_the_note(self):
        values = settings(run(fixture("uniform"), Y="Impulse", Smoothing=cp.SAVITZKY_GOLAY))
        self.assertEqual((values["Half-window"], values["Polynomial degree"], values["Window points"]), (2, 2, 5))
        self.assertIn("descriptive transformation", values["Note"])
        self.assertNotIn("Baseline", values)

    def test_the_figure_has_one_legend_entry_and_never_draws_across_a_gap(self):
        frame = pd.DataFrame({"X": np.arange(12.), "Y": [1, 4, 9, 16, None, 36, 49, 64, None, 100, None, None]})
        figure = run(frame, Operation=cp.FIRST).figure
        axes = figure.axes[0]
        self.assertEqual(axes.get_title(), "First difference")
        line = axes.lines[0]
        x, y = line.get_xdata(), line.get_ydata()
        # Blocks are separated by NaN, so no segment joins two blocks.
        self.assertEqual(np.isnan(x).sum(), 1)
        self.assertTrue((np.isnan(x) == np.isnan(y)).all())
        finite = ~np.isnan(x)
        cut = int(np.flatnonzero(~finite)[0])
        self.assertTrue((x[:cut] < 4).all() and (x[cut + 1:] > 4).all())
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["First difference"])

    def test_identity_with_smoothing_overlays_the_original_points(self):
        figure = run(fixture("uniform"), Y="Impulse", Smoothing=cp.SAVITZKY_GOLAY).figure
        axes = figure.axes[0]
        self.assertEqual(axes.get_title(), "Identity + Savitzky–Golay")
        labels = [text.get_text() for text in axes.get_legend().get_texts()]
        self.assertEqual(labels, ["Identity + Savitzky–Golay", "Original data"])
        self.assertEqual(len(axes.collections[0].get_offsets()), 9)
        # Rates and areas have another unit, so nothing is overlaid.
        other = run(fixture("uniform"), Y="Clean", Operation=cp.FIRST, Smoothing=cp.SAVITZKY_GOLAY).figure.axes[0]
        self.assertEqual(len(other.collections), 0)
        self.assertEqual(other.get_ylabel(), "ΔClean / ΔX")

    def test_a_curve_of_lone_points_is_still_drawn(self):
        frame = pd.DataFrame({"X": np.arange(200.), "Y": [1., None] * 100})
        axes = run(frame).figure.axes[0]
        self.assertEqual(len(axes.lines), 2)
        self.assertEqual(int((~np.isnan(axes.lines[1].get_xdata())).sum()), 100)
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Identity"])
        # A short result marks its points on the one line instead.
        short = run(pd.DataFrame({"X": np.arange(20.), "Y": [1., None] * 10})).figure.axes[0]
        self.assertEqual((len(short.lines), short.lines[0].get_marker()), (1, "o"))


class Size(unittest.TestCase):
    def test_fifty_thousand_rows_in_blocks_are_fast_and_bounded(self):
        rows = 50_000
        x = np.arange(rows) * .01
        y = 3 * x ** 2 - 2 * x + 1
        y[np.arange(1000, rows, 1000)] = np.nan
        frame = pd.DataFrame({"X": x, "Y": y})
        for extra in ({"Operation": cp.FIRST, "Smoothing": cp.SAVITZKY_GOLAY, "Half-window": 50, "Polynomial degree": 6},
                      {"Operation": cp.CUMULATIVE}, {"Operation": cp.SECOND}):
            tracemalloc.start()
            started = time.perf_counter()
            result = run(frame, **extra)
            elapsed = time.perf_counter() - started
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            self.assertLess(elapsed, 15, extra)
            self.assertLess(peak, 200 * 2 ** 20, extra)
            self.assertGreater(len(result.tables["Curve"]), 40_000)
        # A quadratic is reproduced by a quadratic filter: first difference of 3x² − 2x + 1 is 6·x_mid − 2.
        table = curve(frame.iloc[:1000], Operation=cp.FIRST, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 25})
        np.testing.assert_allclose(table["Value"], 6 * table["X"] - 2, rtol=1e-6, atol=1e-6)

    def test_many_small_blocks_do_not_slow_the_cumulative_value_down(self):
        rows = 50_000
        frame = pd.DataFrame({"X": np.arange(rows, dtype=float), "Y": np.where(np.arange(rows) % 3 == 2, np.nan, 1.0)})
        started = time.perf_counter()
        table = curve(frame, Operation=cp.CUMULATIVE)
        self.assertLess(time.perf_counter() - started, 15)
        self.assertEqual(table["Block"].max(), rows // 3 + (1 if rows % 3 else 0))
        self.assertTrue((table.groupby("Block")["Value"].first() == 0).all())


if __name__ == "__main__":
    unittest.main()
