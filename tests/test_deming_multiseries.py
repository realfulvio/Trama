"""Deming regression 0.93: known SDs, several Y series and projections."""
from fractions import Fraction
import unittest
from unittest.mock import patch

from matplotlib.collections import LineCollection
import numpy as np
import pandas as pd

from analisi import exploration
from analisi.deming import (KNOWN_SDS, PROJECTED_COLUMNS, RATIO_HIGH, RATIO_LOW, SERIES_LIMIT, analyse_fit,
                            jackknife_deming, known_ratio, project_points, read_settings)
from analisi.deming_plot import MARKERS, PALETTE, deming_result
from analisi.field_error import FieldError
from analisi.workbench import analyse

NAN = np.nan
BASE = {"X": "Dose", "Y": "A", "Y / X error variance": 0.25}
SERIES = {**BASE, "Uncertainty input": "Known SDs", "X error SD": 2.0, "Y error SD": 1.0,
          "Y series": ["A", "B $"], "Show projections": True}


def frame():
    return pd.DataFrame({"Dose": [0, 1, 2, 4, 7], "A": [4, 3, 7, 7, 15], "B $": [8, NAN, 6, 3, 1]})


def oracle(x, y, sd_x, sd_y):
    """Independent reference: whiten by the SDs, take the principal direction by SVD, project, scale back."""
    values = np.column_stack((x, y)).astype(float)
    sd = np.array([sd_x, sd_y], dtype=float)
    whitened = values / sd
    centre = whitened.mean(axis=0)
    direction = np.linalg.svd(whitened - centre, full_matrices=False)[2][0]
    unit = direction * sd
    slope = unit[1] / unit[0]
    mean_x, mean_y = centre * sd
    projection = (centre + np.outer((whitened - centre) @ direction, direction)) * sd
    return slope, mean_y - slope * mean_x, projection


def run(options):
    return analyse("Deming regression", frame(), options)


class KnownSds(unittest.TestCase):
    def test_ratio_is_the_squared_quotient_and_ignores_the_variance_field(self):
        self.assertEqual(known_ratio(2.0, 1.0), 0.25)
        self.assertEqual(known_ratio(1.0, 3.0), 9.0)
        result = run({**BASE, "Y / X error variance": 123.0, "Uncertainty input": "Known SDs",
                      "X error SD": 2.0, "Y error SD": 1.0})
        report = result.tables["Deming regression"]["Value"]
        self.assertEqual(report["Y / X measurement error variance"], 0.25)
        self.assertEqual(list(result.tables["Deming regression"].index),
                         ["N", "Slope", "Intercept", "Y / X measurement error variance", "X error SD", "Y error SD"])
        self.assertEqual((report["X error SD"], report["Y error SD"]), (2.0, 1.0))
        slope, intercept, _ = oracle(frame()["Dose"], frame()["A"], 2.0, 1.0)
        np.testing.assert_allclose(float(report["Slope"]), slope, rtol=1e-12)
        np.testing.assert_allclose(float(report["Intercept"]), intercept, rtol=1e-12)

    def test_variance_ratio_mode_ignores_the_sd_fields(self):
        plain = run(BASE).tables["Deming regression"]
        with_sds = run({**BASE, "Uncertainty input": "Variance ratio", "X error SD": 9.0,
                        "Y error SD": 0.0}).tables["Deming regression"]
        pd.testing.assert_frame_equal(plain, with_sds, check_exact=True)

    def test_a_common_scale_cancels_before_it_can_underflow(self):
        reference = run(SERIES).tables["Pairs"]
        for scale in (1e-80, 1e-150, 1e150, 1e200):
            scaled = run({**SERIES, "X error SD": 2.0 * scale, "Y error SD": scale}).tables["Pairs"]
            pd.testing.assert_frame_equal(reference, scaled, rtol=1e-10, atol=1e-11)
        self.assertEqual(known_ratio(2e-200, 1e-200), 0.25)
        self.assertEqual(known_ratio(2e200, 1e200), 0.25)

    def test_unrepresentable_ratios_are_refused_on_the_y_sd_field(self):
        for x_sd, y_sd in ((1e-200, 1e200), (1e200, 1e-200), (1e-160, 1e160), (1e155, 1e-155)):
            with self.assertRaises(FieldError) as caught:
                known_ratio(x_sd, y_sd)
            self.assertEqual(caught.exception.field, "Y error SD")
        self.assertLessEqual(known_ratio(1.0, 1e153), RATIO_HIGH)
        self.assertGreaterEqual(known_ratio(1e153, 1.0), RATIO_LOW)

    def test_swapping_x_and_y_inverts_lambda(self):
        data = frame()
        forward = analyse_fit(data, {"X": "Dose", "Y": "A", "Uncertainty input": "Known SDs",
                                     "X error SD": 2.0, "Y error SD": 1.0}).series[0]
        swapped_data = data.rename(columns={"Dose": "Y0", "A": "X0"})
        backward = analyse_fit(swapped_data, {"X": "X0", "Y": "Y0", "Uncertainty input": "Known SDs",
                                              "X error SD": 1.0, "Y error SD": 2.0}).series[0]
        np.testing.assert_allclose(backward.slope, 1.0 / forward.slope, rtol=1e-12)
        np.testing.assert_allclose(backward.intercept, -forward.intercept / forward.slope, rtol=1e-12)
        np.testing.assert_allclose(backward.x, forward.y)

    def test_fields_name_the_problem(self):
        cases = {"X error SD": (0, -1, NAN, np.inf, True, "2", None),
                 "Y error SD": (0, -1, NAN, np.inf, True, "1", None)}
        for field, values in cases.items():
            for value in values:
                options = {**SERIES, field: value}
                if value is None:
                    options.pop(field)
                with self.subTest(field=field, value=value):
                    with self.assertRaises(FieldError) as caught:
                        run(options)
                    self.assertEqual(caught.exception.field, field)
        with self.assertRaises(FieldError) as caught:
            run({**SERIES, "Uncertainty input": "Known SD"})
        self.assertEqual(caught.exception.field, "Uncertainty input")


class Projections(unittest.TestCase):
    def test_matches_the_whitened_svd_oracle_for_every_series_end_to_end(self):
        pairs = run(SERIES).tables["Pairs"]
        for name, column in (("A", "A"), ("B $", "B $")):
            complete = frame()[["Dose", column]].dropna()
            slope, intercept, projection = oracle(complete["Dose"], complete[column], 2.0, 1.0)
            part = pairs[pairs["Series"] == name]
            np.testing.assert_allclose(part[list(PROJECTED_COLUMNS)], projection, rtol=1e-10, atol=1e-11)
            np.testing.assert_allclose(part["Projected Y"], intercept + slope * part["Projected X"], atol=1e-10)

    def test_projection_minimises_the_weighted_distance(self):
        rng = np.random.default_rng(5)
        x = rng.normal(size=40)
        y = 1.5 * x + rng.normal(size=40)
        ratio, slope, intercept = 0.7, 1.3, 0.2
        px, py = project_points(x, y, slope, intercept, ratio)
        on_line = intercept + slope * px
        np.testing.assert_allclose(py, on_line, atol=1e-12)
        best = ratio * (x - px) ** 2 + (y - py) ** 2
        for shift in (-1e-3, 1e-3):
            qx = px + shift
            other = ratio * (x - qx) ** 2 + (y - (intercept + slope * qx)) ** 2
            self.assertTrue(np.all(other >= best))

    def test_lambda_one_is_the_euclidean_perpendicular(self):
        x, y = np.array([0.0, 2.0, 5.0]), np.array([1.0, -1.0, 3.0])
        slope, intercept = -0.5, 1.5
        px, py = project_points(x, y, slope, intercept, 1.0)
        normal = np.array([-slope, 1.0]) / np.hypot(slope, 1.0)
        for index in range(3):
            step = np.array([px[index] - x[index], py[index] - y[index]])
            np.testing.assert_allclose(step, normal * (step @ normal), atol=1e-12)

    def test_points_on_the_line_have_zero_length_segments(self):
        x = np.array([0.0, 1.0, 2.0, 3.0])
        y = 3.0 - 2.0 * x
        px, py = project_points(x, y, -2.0, 3.0, 4.0)
        np.testing.assert_array_equal(px, x)
        np.testing.assert_array_equal(py, y)
        result = analyse("Deming regression", pd.DataFrame({"x": x, "y": y + np.array([0, 0.5, -0.5, 0])}),
                         {"X": "x", "Y": "y", "Y / X error variance": 1.0, "Show projections": True})
        pairs = result.tables["Pairs"]
        self.assertEqual(list(pairs.columns)[-2:], list(PROJECTED_COLUMNS))
        self.assertNotIn("Series", pairs)

    def test_negative_slope_and_horizontal_fit(self):
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([5.0, 3.5, 2.0]) + np.array([0.3, -0.2, 0.1])
        px, py = project_points(x, y, -1.5, 6.5, 2.0)
        np.testing.assert_allclose(py, 6.5 - 1.5 * px, atol=1e-12)
        # The projection moves each point toward the line: the vertical gap shrinks and keeps its sign.
        before, after = y - (6.5 - 1.5 * x), py - (6.5 - 1.5 * px)
        self.assertTrue(np.all(np.abs(after) < 1e-12))
        self.assertTrue(np.all(np.sign(before) == np.sign(y - py)))
        px0, py0 = project_points(x, y, 0.0, 2.0, 3.0)
        np.testing.assert_array_equal(px0, x)
        np.testing.assert_allclose(py0, 2.0)

    def test_exact_rational_oracle_for_ordinary_and_extreme_lines(self):
        cases = ((0.37, 1.5, -2.0, 1.2), (4.5e300, 1e200, 3.0, 2e100), (3e-300, 1e-200, 5.0, -7.0),
                 (1.0, 1e250, 3.0, 5.0), (1e300, 1e-100, 2.0, 5.0))
        for ratio, slope, intercept, y in cases:
            x = 0.75
            with self.subTest(ratio=ratio, slope=slope):
                px, py = project_points([x], [y], slope, intercept, ratio)
                fx, fy, fa, fb, fl = map(Fraction, (x, y, intercept, slope, ratio))
                r = fy - fa - fb * fx
                want_x = fx + fb * r / (fl + fb * fb)
                want_y = fy - fl * r / (fl + fb * fb)
                # Where x* nearly cancels against x the result is exact only to the scale of the data.
                np.testing.assert_allclose(px[0], float(want_x), rtol=1e-9, atol=1e-13 * abs(x))
                np.testing.assert_allclose(py[0], float(want_y), rtol=1e-9,
                                           atol=1e-13 * max(abs(y), abs(intercept), abs(float(want_y))))

    def test_representation_limits_stop_instead_of_drawing_nan(self):
        with self.assertRaises(ValueError):
            project_points([1e308], [-1e308], 1e10, 1e308, 1.0)
        with self.assertRaises(ValueError):
            project_points([1.0], [2.0], 1.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            project_points([1.0], [2.0], np.inf, 0.0, 1.0)
        with self.assertRaises(ValueError):
            project_points([NAN], [2.0], 1.0, 0.0, 1.0)
        with self.assertRaises(ValueError):
            project_points([1.0, 2.0], [2.0], 1.0, 0.0, 1.0)

    def test_pairs_keep_source_rows_and_never_fill_missing_values_with_zero(self):
        pairs = run(SERIES).tables["Pairs"]
        self.assertEqual(list(pairs["Source row"]), [0, 1, 2, 3, 4, 0, 2, 3, 4])
        self.assertEqual(list(pairs.columns), ["Series", "Source row", "X", "Y", "Fitted Y",
                                               "Vertical residual (Y − fitted)", "Projected X", "Projected Y"])
        edited = frame()
        edited.loc[2, "A"] = NAN
        again = analyse("Deming regression", edited, SERIES).tables["Pairs"]
        self.assertEqual(list(again.loc[again["Series"] == "A", "Source row"]), [0, 1, 3, 4])
        self.assertEqual(list(again.loc[again["Series"] == "B $", "Source row"]), [0, 2, 3, 4])

    def test_projections_off_adds_no_columns(self):
        pairs = run({**SERIES, "Show projections": False}).tables["Pairs"]
        self.assertNotIn("Projected X", pairs)
        self.assertEqual(list(pairs.columns)[:2], ["Series", "Source row"])


class SeveralSeries(unittest.TestCase):
    def test_tables_follow_the_series_order_and_the_oracle(self):
        result = run(SERIES)
        self.assertEqual(list(result.tables), ["Deming regression", "Data", "Pairs"])
        table = result.tables["Deming regression"]
        self.assertEqual(list(table.columns), ["Series", "N", "Slope", "Intercept",
                                               "Y / X measurement error variance"])
        self.assertEqual(list(table["Series"]), ["A", "B $"])
        self.assertEqual(list(table["N"]), [5, 4])
        for name, column in (("A", "A"), ("B $", "B $")):
            complete = frame()[["Dose", column]].dropna()
            slope, intercept, _ = oracle(complete["Dose"], complete[column], 2.0, 1.0)
            row = table[table["Series"] == name].iloc[0]
            np.testing.assert_allclose(row["Slope"], slope, rtol=1e-10)
            np.testing.assert_allclose(row["Intercept"], intercept, rtol=1e-10)
            self.assertEqual(row["Y / X measurement error variance"], 0.25)
        data = result.tables["Data"]
        self.assertEqual(list(data.columns), ["Series", "X", "Y"])
        self.assertEqual(list(data["Series"]), ["A"] * 5 + ["B $"] * 4)
        self.assertEqual(list(data["Y"]), [4, 3, 7, 7, 15, 8, 6, 3, 1])

    def test_series_order_is_the_serialised_order_and_a_single_column_is_allowed(self):
        reversed_order = run({**SERIES, "Y series": ["B $", "A"]})
        self.assertEqual(list(reversed_order.tables["Deming regression"]["Series"]), ["B $", "A"])
        one = run({**SERIES, "Y series": ["B $"]})
        self.assertEqual(list(one.tables["Deming regression"]["Series"]), ["B $"])
        self.assertEqual(one.figure.axes[0].get_ylabel(), "B $")
        self.assertEqual(run(SERIES).figure.axes[0].get_ylabel(), "Y")

    def test_y_series_ignores_the_single_y_and_an_empty_list_inherits_it(self):
        only_b = run({**SERIES, "Y": "A", "Y series": ["B $"]}).tables["Deming regression"]
        self.assertEqual(list(only_b["Series"]), ["B $"])
        inherited = run({**SERIES, "Y series": [], "Show projections": False})
        self.assertEqual(list(inherited.tables["Deming regression"].index),
                         ["N", "Slope", "Intercept", "Y / X measurement error variance", "X error SD", "Y error SD"])
        self.assertEqual(list(inherited.tables["Data"].columns), ["Dose", "A"])

    def test_each_series_is_fitted_once_and_reuses_the_result_for_intervals(self):
        options = {**SERIES, "Parameter intervals": "Jackknife (t)", "Confidence level (%)": 90.0}
        with patch("analisi.deming.exploration.deming", wraps=exploration.deming) as spy:
            result = run(options)
        self.assertEqual(spy.call_count, 2)
        table = result.tables["Deming regression"]
        self.assertEqual(list(table.columns)[5:], ["Interval", "Confidence level (%)", "df", "Slope SE", "Slope CI low",
                                                   "Slope CI high", "Intercept SE", "Intercept CI low",
                                                   "Intercept CI high"])
        row = table[table["Series"] == "A"].iloc[0]
        report, _, _ = jackknife_deming(frame(), "Dose", "A", 0.25, intervals="Jackknife (t)", level=90.0)
        for key in ("Slope", "Slope SE", "Slope CI low", "Intercept CI high", "df", "Confidence level (%)"):
            self.assertEqual(row[key], report[key], key)
        self.assertTrue(np.isfinite(table[table["Series"] == "B $"].iloc[0]["Slope SE"]))

    def test_a_series_too_short_for_intervals_keeps_its_fit(self):
        data = frame()
        data["C"] = [1.0, 2.0, NAN, 3.5, NAN]
        result = analyse("Deming regression", data, {**SERIES, "Y series": ["A", "C"],
                                                     "Parameter intervals": "Jackknife (t)"})
        table = result.tables["Deming regression"]
        short = table[table["Series"] == "C"].iloc[0]
        self.assertTrue(short["Interval status"].startswith("Interval unavailable"))
        self.assertTrue(np.isnan(short["Slope SE"]))
        self.assertEqual(short["N"], 3)
        self.assertEqual(table[table["Series"] == "A"].iloc[0]["Interval status"], "")

    def test_the_variance_ratio_is_shared_when_the_input_is_a_ratio(self):
        options = {**BASE, "Y series": ["A", "B $"]}
        table = run(options).tables["Deming regression"]
        self.assertEqual(list(table["Y / X measurement error variance"]), [0.25, 0.25])
        for name in ("A", "B $"):
            complete = frame()[["Dose", name]].dropna()
            expected, _ = exploration.deming(complete, "Dose", name, 0.25)
            self.assertEqual(table[table["Series"] == name].iloc[0]["Slope"], expected["Slope"])

    def test_input_frame_is_not_modified(self):
        data = frame()
        original = data.copy()
        analyse("Deming regression", data, SERIES)
        pd.testing.assert_frame_equal(data, original)

    def test_twelve_series_is_the_limit(self):
        rng = np.random.default_rng(1)
        wide = pd.DataFrame({"x": np.arange(10.0), **{f"s{i}": np.arange(10.0) * (i + 1) + rng.normal(size=10)
                                                    for i in range(SERIES_LIMIT + 1)}})
        names = [f"s{i}" for i in range(SERIES_LIMIT)]
        result = analyse("Deming regression", wide, {"X": "x", "Y": "s0", "Y / X error variance": 1.0,
                                                    "Y series": names, "Show projections": True})
        self.assertEqual(len(result.tables["Deming regression"]), SERIES_LIMIT)
        self.assertEqual(sum(isinstance(item, LineCollection) for item in result.figure.axes[0].collections),
                         SERIES_LIMIT)
        with self.assertRaises(FieldError) as caught:
            analyse("Deming regression", wide, {"X": "x", "Y": "s0", "Y / X error variance": 1.0,
                                               "Y series": [*names, f"s{SERIES_LIMIT}"]})
        self.assertEqual(caught.exception.field, "Y series")


class Validation(unittest.TestCase):
    def check(self, options, field, text=None, data=None):
        with self.assertRaises(FieldError) as caught:
            analyse("Deming regression", frame() if data is None else data, options)
        self.assertEqual(caught.exception.field, field, str(caught.exception))
        if text is not None:
            self.assertIn(text, str(caught.exception))
        return str(caught.exception)

    def test_y_series_membership_errors_stay_on_the_field(self):
        self.check({**SERIES, "Y series": ["A", "A"]}, "Y series", '"A"')
        self.check({**SERIES, "Y series": ["A", "Dose"]}, "Y series", '"Dose"')
        self.check({**SERIES, "Y series": ["A", "Missing"]}, "Y series", '"Missing"')
        self.check({**SERIES, "Y series": "A"}, "Y series")
        self.check({**SERIES, "Y series": ["A", 3]}, "Y series")
        self.check({**SERIES, "Y series": {"A": 1}}, "Y series")

    def test_a_short_or_degenerate_series_is_named(self):
        data = frame()
        data["Short"] = [1.0, NAN, 2.0, NAN, NAN]
        data["Flat"] = [3.0] * 5
        data["Text"] = ["a", "b", "c", "d", "e"]
        self.check({**SERIES, "Y series": ["A", "Short"]}, "Y series", 'Series "Short" has 2 complete pairs', data)
        self.check({**SERIES, "Y series": ["A", "Flat"]}, "Y series", 'Series "Flat" cannot be fitted', data)
        self.check({**SERIES, "Y series": ["Text", "A"]}, "Y series", 'Series "Text" contains non-numeric', data)
        data["Blank"] = [NAN] * 5
        self.check({**SERIES, "Y series": ["Blank", "A"]}, "Y series", 'Series "Blank" has 0 complete pairs', data)
        data["Dose"] = data["Dose"].astype(object)
        data.loc[0, "Dose"] = "high"
        self.check({**SERIES, "Y series": ["A"]}, "X", 'Column "Dose"', data)

    def test_other_fields_keep_their_own_names(self):
        self.check({**SERIES, "Y / X error variance": 0, "Uncertainty input": "Variance ratio"},
                   "Y / X error variance")
        options = {**SERIES, "Uncertainty input": "Variance ratio"}
        options.pop("Y / X error variance")
        self.check(options, "Y / X error variance")
        self.check({**SERIES, "Parameter intervals": "Bootstrap"}, "Parameter intervals")
        for level in (0, 100, NAN, "high"):
            self.check({**SERIES, "Parameter intervals": "Jackknife (t)", "Confidence level (%)": level},
                       "Confidence level (%)")
        self.check({**SERIES, "Show projections": "False"}, "Show projections")
        self.check({**SERIES, "X": "Nope"}, "X", '"Nope"')

    def test_projection_overflow_is_reported_on_the_series(self):
        data = pd.DataFrame({"x": [1e307, 2e307, -1e307, 0.0], "y": [-1e307, 1e307, 2e307, 5.0]})
        text = self.check({"X": "x", "Y": "y", "Y / X error variance": 1.0, "Y series": ["y"],
                           "Show projections": True}, "Y series", data=data)
        self.assertTrue('"y"' in text)

    def test_read_settings_flags_legacy_recipes(self):
        legacy = read_settings(frame(), BASE)
        self.assertFalse(legacy.extended)
        explicit = read_settings(frame(), {**BASE, "Uncertainty input": "Variance ratio", "Y series": [],
                                           "Show projections": False})
        self.assertFalse(explicit.extended)
        self.assertTrue(read_settings(frame(), SERIES).extended)
        self.assertEqual(read_settings(frame(), SERIES).ratio, 0.25)
        self.assertEqual(KNOWN_SDS, "Known SDs")


class Legacy(unittest.TestCase):
    def test_historical_recipe_and_explicit_defaults_give_the_same_sheets(self):
        plain = run(BASE)
        explicit = run({**BASE, "Uncertainty input": "Variance ratio", "Y series": [], "Show projections": False})
        self.assertEqual(list(plain.tables), ["Deming regression", "Data", "Pairs"])
        for name in plain.tables:
            pd.testing.assert_frame_equal(plain.tables[name], explicit.tables[name], check_exact=True)
        self.assertNotIn("Projected X", plain.tables["Pairs"])
        report, points = exploration.deming(frame(), "Dose", "A", 0.25)
        for key, value in report.items():
            self.assertEqual(plain.tables["Deming regression"]["Value"][key], value)
        self.assertEqual(list(plain.tables["Data"].columns), ["Dose", "A"])

    def test_historical_figure_geometry(self):
        for options in (BASE, {**BASE, "Identity line": True}):
            figure = run(options).figure
            axes = figure.axes[0]
            report, points = exploration.deming(frame(), "Dose", "A", 0.25)
            np.testing.assert_array_equal(axes.collections[0].get_offsets(), points[["Dose", "A"]].to_numpy())
            self.assertFalse(any(isinstance(item, LineCollection) for item in axes.collections))
            fit = axes.lines[0]
            if options.get("Identity line"):
                low, high = 0.0, 15.0
                self.assertEqual(tuple(axes.get_xlim()), (low, high))
                self.assertEqual(tuple(axes.get_ylim()), (low, high))
                self.assertEqual([line.get_label() for line in axes.lines], ["Deming fit", "Identity"])
                self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Deming fit", "Identity"])
            else:
                self.assertIsNone(axes.get_legend())
                np.testing.assert_array_equal(fit.get_xdata(), [0, 7])
            np.testing.assert_allclose(fit.get_ydata(), report["Intercept"] + report["Slope"] * fit.get_xdata())
            self.assertEqual((axes.get_xlabel(), axes.get_ylabel(), axes.get_title()), ("Dose", "A", "Deming regression"))

    def test_single_series_with_projections_keeps_the_historical_sheets_and_adds_segments(self):
        result = run({**BASE, "Show projections": True})
        plain = run(BASE)
        pd.testing.assert_frame_equal(result.tables["Data"], plain.tables["Data"], check_exact=True)
        pd.testing.assert_frame_equal(result.tables["Pairs"].iloc[:, :5], plain.tables["Pairs"], check_exact=True)
        pd.testing.assert_frame_equal(result.tables["Deming regression"], plain.tables["Deming regression"],
                                      check_exact=True)
        axes = result.figure.axes[0]
        collections = [item for item in axes.collections if isinstance(item, LineCollection)]
        self.assertEqual(len(collections), 1)
        self.assertEqual(len(collections[0].get_segments()), 5)


class Drawing(unittest.TestCase):
    def test_one_line_collection_per_series_in_the_series_colour_below_the_points(self):
        axes = run(SERIES).figure.axes[0]
        collections = [item for item in axes.collections if isinstance(item, LineCollection)]
        points = [item for item in axes.collections if not isinstance(item, LineCollection)]
        self.assertEqual([len(item.get_segments()) for item in collections], [5, 4])
        for index, (collection, scatter) in enumerate(zip(collections, points, strict=True)):
            self.assertLess(collection.get_zorder(), scatter.get_zorder())
            np.testing.assert_allclose(collection.get_colors()[0][:3],
                                       np.array(self.rgb(PALETTE[index])), atol=1e-6)
            self.assertEqual(len(scatter.get_offsets()), (5, 4)[index])
        fits = [line for line in axes.lines if line.get_linestyle() == "-"]
        self.assertEqual(len(fits), 2)
        self.assertGreater(min(line.get_zorder() for line in fits), collections[0].get_zorder())

    @staticmethod
    def rgb(color):
        return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def test_literal_legend_one_identity_line_and_the_shared_domain(self):
        result = run({**SERIES, "Identity line": True, "Y series": ["A", "B $"]})
        axes = result.figure.axes[0]
        legend = axes.get_legend()
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["A", "B $", "Identity"])
        self.assertFalse(any(text.get_parse_math() for text in legend.get_texts()))
        self.assertFalse(axes.xaxis.label.get_parse_math() or axes.yaxis.label.get_parse_math())
        dashed = [line for line in axes.lines if line.get_linestyle() == "--"]
        self.assertEqual(len(dashed), 1)
        self.assertEqual(tuple(axes.get_xlim()), (0.0, 15.0))
        self.assertEqual(tuple(axes.get_ylim()), (0.0, 15.0))
        for line in axes.lines:
            self.assertEqual(tuple(line.get_xdata()), (0.0, 15.0))

    def test_identity_uses_only_values_that_a_series_used(self):
        data = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0, 50.0],
                             "a": [0.0, 1.2, 2.0, 2.9, 4.1, NAN],
                             "b": [0.5, 1.5, 2.4, 3.6, 4.5, NAN]})
        options = {"X": "x", "Y": "a", "Y / X error variance": 1.0, "Y series": ["a", "b"], "Identity line": True}
        axes = analyse("Deming regression", data, options).figure.axes[0]
        self.assertEqual((tuple(axes.get_xlim()), tuple(axes.get_ylim())), ((0.0, 4.5),) * 2)
        data.loc[5, "a"] = 49.0
        data.loc[5, "b"] = 51.0
        axes = analyse("Deming regression", data, options).figure.axes[0]
        self.assertEqual((tuple(axes.get_xlim()), tuple(axes.get_ylim())), ((0.0, 51.0),) * 2)

    def test_dollar_signs_in_series_names_are_not_mathtext(self):
        data = frame().rename(columns={"A": "$a$ vs $b$"})
        figure = analyse("Deming regression", data, {**SERIES, "Y": "$a$ vs $b$",
                                                      "Y series": ["$a$ vs $b$", "B $"]}).figure
        texts = [text.get_text() for text in figure.axes[0].get_legend().get_texts()]
        self.assertEqual(texts[0], "$a$ vs $b$")
        figure.canvas.draw()
        single = analyse("Deming regression", data, {**BASE, "Y": "$a$ vs $b$", "Show projections": True}).figure
        self.assertEqual(single.axes[0].get_ylabel(), "$a$ vs $b$")
        self.assertFalse(single.axes[0].yaxis.label.get_parse_math())

    def test_palette_and_markers_cover_the_series_limit(self):
        self.assertGreaterEqual(len(PALETTE), SERIES_LIMIT)
        self.assertGreaterEqual(len(MARKERS), SERIES_LIMIT)
        self.assertEqual(len(set(PALETTE)), len(PALETTE))
        self.assertEqual(len(set(MARKERS)), len(MARKERS))

    def test_the_figure_renders(self):
        result = deming_result(frame(), {**SERIES, "Identity line": True})
        result.figure.canvas.draw()


if __name__ == "__main__":
    unittest.main()
