"""Estimated marginal means of the fixed-effects Multifactor ANOVA.

The unbalanced oracle distinguishes a uniform marginal mean from the raw mean of the rows.
A missing cell is estimated from an additive model and checked against a separate least-squares
oracle written in this file.
"""
import json
import math
from itertools import product
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi import anova_marginal_means as means
from analisi.anova_planned_contrasts import NOT_ESTIMABLE, OK
from analisi.field_error import FieldError
from analisi.stats import _factorial_anova_components

ORACLE = json.loads((Path(__file__).parent / "data" / "marginal_means" / "oracolo.json").read_text(encoding="utf-8"))
METHOD_FACTORS = ["A", "B"]


def oracle_frame():
    return pd.DataFrame(ORACLE["data"])


def fitted(frame, factors, order=2, terms=None):
    _table, _fit, data, design, beta, error, df = _factorial_anova_components(
        frame, "Y", factors, order, terms=terms)
    return data, design, beta, error, df


def components_sheet(frame, fit_factors, chosen, *, order=2, terms=None, overall=False, confidence=0.95):
    data, design, beta, error, df = fitted(frame, fit_factors, order, terms)
    return means.sheet((list(chosen), overall, confidence), list(fit_factors), data, design, beta, error, df)


def cell(sheet, **levels):
    mask = sheet[means.MEAN].eq(means.COMBINATION)
    for name, level in levels.items():
        mask &= sheet[name].eq(level)
    rows = sheet.loc[mask]
    if len(rows) != 1:
        raise AssertionError(f"{levels} matched {len(rows)} rows")
    return rows.iloc[0]


def overall(sheet):
    rows = sheet.loc[sheet[means.MEAN].eq(means.GRAND)]
    if len(rows) != 1:
        raise AssertionError(f"overall matched {len(rows)} rows")
    return rows.iloc[0]


def assert_close(test, row, expected):
    test.assertEqual(row[means.STATUS], OK)
    test.assertEqual(row[means.REASON], "")
    test.assertEqual(row[means.WEIGHTING], means.WEIGHTING_TEXT)
    for column, key in (("Estimate", "mean"), ("SE", "se"), ("df", "df"), ("CI low", "low"), ("CI high", "high")):
        test.assertTrue(math.isclose(row[column], expected[key], rel_tol=0, abs_tol=1e-10),
                        f"{column}: {row[column]} != {expected[key]}")


class OracleTests(unittest.TestCase):
    def test_cells_marginals_and_overall_match_the_oracle(self):
        frame = oracle_frame()
        cells = components_sheet(frame, METHOD_FACTORS, METHOD_FACTORS, overall=True)
        self.assertEqual(cells[means.MEAN].tolist(), [means.COMBINATION] * 4 + [means.GRAND])
        for levels, label in ((("A0", "B0"), "A0 B0"), (("A0", "B1"), "A0 B1"),
                              (("A1", "B0"), "A1 B0"), (("A1", "B1"), "A1 B1")):
            assert_close(self, cell(cells, A=levels[0], B=levels[1]), ORACLE["expected"][label])
        assert_close(self, overall(cells), ORACLE["expected"]["Globale"])
        for factor, labels in (("A", ("A0", "A1")), ("B", ("B0", "B1"))):
            marginal = components_sheet(frame, METHOD_FACTORS, [factor])
            self.assertEqual(marginal[factor].tolist(), list(labels))
            for label in labels:
                assert_close(self, cell(marginal, **{factor: label}), ORACLE["expected"][label])
        only = components_sheet(frame, METHOD_FACTORS, [], overall=True)
        self.assertEqual(list(only.columns), [means.MEAN, *means.STAT_COLUMNS])
        assert_close(self, overall(only), ORACLE["expected"]["Globale"])

    def test_uniform_marginal_is_not_the_raw_mean(self):
        frame = oracle_frame()
        row = cell(components_sheet(frame, METHOD_FACTORS, ["A"]), A="A0")
        raw = float(frame.loc[frame.A == "A0", "Y"].mean())
        self.assertAlmostEqual(row["Estimate"], 5.0, delta=1e-10)
        self.assertAlmostEqual(raw, 6.0, delta=1e-12)
        self.assertGreater(abs(row["Estimate"] - raw), 0.5)

    def test_confidence_changes_only_the_interval(self):
        frame = oracle_frame()
        wider = cell(components_sheet(frame, METHOD_FACTORS, ["A"], confidence=0.99), A="A0")
        narrow = cell(components_sheet(frame, METHOD_FACTORS, ["A"], confidence=0.8), A="A0")
        self.assertAlmostEqual(wider["Estimate"], narrow["Estimate"], delta=1e-12)
        self.assertAlmostEqual(wider["SE"], narrow["SE"], delta=1e-12)
        self.assertLess(wider["CI low"], narrow["CI low"])
        self.assertGreater(wider["CI high"], narrow["CI high"])
        self.assertAlmostEqual(wider["Confidence"], 0.99, delta=1e-12)


class AdditiveMissingCellTests(unittest.TestCase):
    def frame(self):
        """The oracle without the A1 × B1 cell."""
        frame = oracle_frame()
        return frame.loc[~((frame.A == "A1") & (frame.B == "B1"))].reset_index(drop=True)

    def test_saturated_model_rejects_the_empty_cell(self):
        with self.assertRaises(ValueError) as raised:
            fitted(self.frame(), METHOD_FACTORS, order=2)
        self.assertIn("rank deficient", str(raised.exception).lower())

    def test_additive_model_estimates_the_missing_cell(self):
        frame = self.frame()
        sheet = components_sheet(frame, METHOD_FACTORS, METHOD_FACTORS, order=1, overall=True)
        expected = additive_oracle(frame, confidence=0.95)
        for levels in product(("A0", "A1"), ("B0", "B1")):
            got = cell(sheet, A=levels[0], B=levels[1])
            want = expected[levels]
            self.assertEqual(got[means.STATUS], OK, levels)
            for column in ("Estimate", "SE", "df", "CI low", "CI high"):
                self.assertTrue(math.isclose(got[column], want[column], rel_tol=0, abs_tol=1e-10),
                                f"{levels} {column}: {got[column]} != {want[column]}")
        # The missing cell is not the average of the observed cells; the additive model fills it in.
        self.assertNotIn(("A1", "B1"), set(zip(frame.A, frame.B)))
        self.assertAlmostEqual(cell(sheet, A="A1", B="B1")["Estimate"], expected[("A1", "B1")]["Estimate"], delta=1e-10)

    def test_selected_terms_use_the_same_additive_fit(self):
        frame = self.frame().assign(C="keep")
        full = components_sheet(frame, METHOD_FACTORS, METHOD_FACTORS, order=1)
        data, design, beta, error, df = fitted(frame, ["A", "B", "C"], terms=[["A"], ["B"]])
        selected = means.sheet((["A", "B"], False, 0.95), ["A", "B"], data, design, beta, error, df)
        pd.testing.assert_frame_equal(selected, full)


def additive_oracle(frame, confidence=0.95):
    """Treatment-coded least squares of ``Y ~ A + B``, then every cell of the 2 × 2 grid.

    The coding is not the ANOVA's sum coding. The cell predictions and their standard errors are
    properties of the model, so they must agree with the sheet anyway.
    """
    from scipy import stats

    a = frame["A"].astype(str).to_numpy()
    b = frame["B"].astype(str).to_numpy()
    y = frame["Y"].to_numpy(float)
    x = np.column_stack([np.ones(len(y)), (a == "A1").astype(float), (b == "B1").astype(float)])
    beta, residuals, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    df = len(y) - int(rank)
    mse = float(residuals[0]) / df
    covariance = np.linalg.pinv(x.T @ x) * mse
    critical = stats.t.ppf(1 - (1 - confidence) / 2, df)
    found = {}
    for a_level, b_level in product(("A0", "A1"), ("B0", "B1")):
        row = np.array([1.0, float(a_level == "A1"), float(b_level == "B1")])
        estimate = float(row @ beta)
        se = math.sqrt(float(row @ covariance @ row))
        found[(a_level, b_level)] = {"Estimate": estimate, "SE": se, "df": float(df),
                                     "CI low": estimate - critical * se, "CI high": estimate + critical * se}
    return found


class NonEstimableTests(unittest.TestCase):
    def test_a_non_estimable_mean_is_blank_and_gives_the_reason(self):
        blank = {"Estimate": np.nan, "SE": np.nan, "df": np.nan, "t": np.nan, "p": np.nan,
                 "CI low": np.nan, "CI high": np.nan, "Status": NOT_ESTIMABLE}
        kept = {"Estimate": 4.0, "SE": 1.0, "df": 3.0, "t": 4.0, "p": 0.02,
                "CI low": 1.0, "CI high": 7.0, "Status": OK}
        sheet = means.present(["A"], [("gone",), ("kept",)], [blank, kept], 0.95)
        missing = cell(sheet, A="gone")
        for column in ("Estimate", "SE", "df", "CI low", "CI high"):
            self.assertTrue(math.isnan(missing[column]), column)
        self.assertEqual(missing[means.STATUS], NOT_ESTIMABLE)
        self.assertEqual(missing[means.REASON], means.REASON_NOT_ESTIMABLE)
        self.assertEqual(missing[means.WEIGHTING], means.WEIGHTING_TEXT)
        self.assertEqual(cell(sheet, A="kept")[means.STATUS], OK)
        self.assertAlmostEqual(cell(sheet, A="kept")["Estimate"], 4.0)


class LiteralAndExclusionTests(unittest.TestCase):
    def test_levels_and_a_reserved_factor_name_stay_literal(self):
        frame = oracle_frame().rename(columns={"A": "Estimate", "B": "B |"})
        frame["Estimate"] = frame["Estimate"].map({"A0": "100%", "A1": 'say "hi"'})
        frame["B |"] = frame["B |"].map({"B0": "µ < 1", "B1": "B |"})
        data, design, beta, error, df = fitted(frame, ["Estimate", "B |"], 2)
        sheet = means.sheet((["B |", "Estimate"], False, 0.95), ["Estimate", "B |"], data, design, beta, error, df)
        self.assertEqual(sheet.columns.tolist()[:3], [means.MEAN, "B |", "Estimate (factor)"])
        self.assertEqual(sorted(zip(sheet["B |"], sheet["Estimate (factor)"])),
                         sorted([("µ < 1", "100%"), ("µ < 1", 'say "hi"'),
                                 ("B |", "100%"), ("B |", 'say "hi"')]))
        self.assertTrue((sheet[means.STATUS] == OK).all())

    def test_a_missing_response_matches_the_row_removed(self):
        frame = oracle_frame()
        masked = frame.copy()
        masked.loc[0, "Y"] = np.nan
        dropped = frame.drop(index=0).reset_index(drop=True)
        left = components_sheet(masked, METHOD_FACTORS, METHOD_FACTORS)
        right = components_sheet(dropped, METHOD_FACTORS, METHOD_FACTORS)
        pd.testing.assert_frame_equal(left, right)
        self.assertNotAlmostEqual(cell(left, A="A0", B="B0")["Estimate"], 2.0, delta=1e-8)

    def test_colliding_category_text_is_a_field_error(self):
        frame = oracle_frame()
        frame["B"] = frame["B"].astype(object)
        frame.loc[frame.B == "B0", "B"] = 1
        frame.loc[frame.index[:1], "B"] = "1"
        with self.assertRaises(FieldError) as raised:
            means.check_request({means.ENABLED: True, means.FACTORS: ["A"], means.OVERALL: False},
                                METHOD_FACTORS, frame, "Y")
        self.assertEqual(raised.exception.field, means.FACTORS)
        self.assertIn("“1”", str(raised.exception))


class ValidationTests(unittest.TestCase):
    def request(self, **changes):
        options = {means.ENABLED: True, means.FACTORS: ["A"], means.OVERALL: False,
                   means.CONFIDENCE: 0.95, **changes}
        return means.check_request(options, METHOD_FACTORS, oracle_frame(), "Y")

    def test_a_factor_outside_the_model_is_rejected(self):
        with self.assertRaises(FieldError) as raised:
            self.request(**{means.FACTORS: ["C"]})
        self.assertEqual(raised.exception.field, means.FACTORS)
        self.assertIn("“C”", str(raised.exception))

    def test_confidence_and_the_empty_choice_are_rejected(self):
        for value in (0, 1, 1.5, -0.2, math.nan, math.inf, True, "0.95"):
            with self.assertRaises(FieldError) as raised:
                self.request(**{means.CONFIDENCE: value})
            self.assertEqual(raised.exception.field, means.CONFIDENCE, value)
        with self.assertRaises(FieldError) as raised:
            self.request(**{means.FACTORS: [], means.OVERALL: False})
        self.assertEqual(raised.exception.field, means.FACTORS)
        with self.assertRaises(FieldError) as raised:
            self.request(**{means.FACTORS: ["A", "A"]})
        self.assertIn("more than once", str(raised.exception))
        with self.assertRaises(FieldError) as raised:
            self.request(**{means.OVERALL: "yes"})
        self.assertEqual(raised.exception.field, means.OVERALL)

    def test_turned_off_and_legacy_recipes_do_not_read_the_other_keys(self):
        self.assertIsNone(means.check_request({}, METHOD_FACTORS, oracle_frame(), "Y"))
        self.assertIsNone(means.check_request(
            {means.ENABLED: False, means.FACTORS: "not a list", means.CONFIDENCE: 9},
            METHOD_FACTORS, oracle_frame(), "Y"))
        self.assertFalse(means.active({}))
        self.assertFalse(means.active({means.ENABLED: False}))
        self.assertTrue(means.active({means.ENABLED: True}))

    def test_reference_grid_limit(self):
        levels = {"A": [str(i) for i in range(64)], "B": [str(i) for i in range(64)]}
        self.assertEqual(means.ensure_grid(levels, ["A", "B"]), 4096)
        levels["B"].append("extra")
        with self.assertRaises(FieldError) as raised:
            means.ensure_grid(levels, ["A", "B"])
        self.assertIn("4096", str(raised.exception))
        self.assertEqual(raised.exception.field, means.FACTORS)

    def test_a_wide_combination_is_rejected_from_the_data(self):
        frame = pd.DataFrame({
            "Y": 1.0,
            "A": np.repeat([f"L{i:02d}" for i in range(65)], 64),
            "B": np.tile([f"M{i:02d}" for i in range(64)], 65),
        })
        with self.assertRaises(FieldError) as raised:
            means.check_request({means.ENABLED: True, means.FACTORS: ["A", "B"], means.OVERALL: True},
                                ["A", "B"], frame, "Y")
        self.assertEqual(raised.exception.field, means.FACTORS)
        self.assertIn("4160", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
