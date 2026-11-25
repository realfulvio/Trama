"""Estimated marginal means of the fixed-effects Multifactor ANOVA.

The oracle is ``tests/data/marginal_means/oracolo.json``: an unbalanced 2 × 2, so the equal-weight
marginal mean is not the raw mean. A missing cell is estimated from an additive model and checked
against an independent least-squares oracle. A mean outside the fitted row space is empty.
"""
import json
from pathlib import Path
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from scipy import stats

from analisi import anova_marginal_means as means
from analisi import stats as engine
from analisi.field_error import FieldError
from analisi.workbench import METHODS, analyse

METHOD = "Multifactor ANOVA"
ORACLE = json.loads((Path(__file__).parent / "data" / "marginal_means" / "oracolo.json").read_text(encoding="utf-8"))
FIELDS = ("Estimate", "SE", "df", "CI low", "CI high")


def oracle_frame():
    return pd.DataFrame(ORACLE["data"])


def fit(frame, factors, order=2, **kwargs):
    _table, _summary, data, design, beta, error, df = engine._factorial_anova_components(
        frame, "Y", factors, order, **kwargs)
    return data, design, beta, error, df


def sheet_of(frame, factors, *, order=2, marginal=None, overall=False, confidence=0.95, **kwargs):
    data, design, beta, error, df = fit(frame, factors, order, **kwargs)
    model = list(factors)
    request = means.check_options({means.ENABLED: True, means.FACTORS: list(marginal if marginal is not None else factors),
                                   means.OVERALL: overall, means.CONFIDENCE: confidence}, model)
    return means.tables(request, model, data, design, beta, error, df)[means.SHEET]


def combination(sheet, **levels):
    mask = pd.Series(True, index=sheet.index)
    if "Mean" in sheet.columns:
        mask &= sheet["Mean"].eq(means.COMBINATION_ROW)
    for name, level in levels.items():
        mask &= sheet[name].eq(level)
    found = sheet.loc[mask]
    if len(found) != 1:
        raise AssertionError(f"{levels} matched {len(found)} rows")
    return found.iloc[0]


def overall(sheet):
    return sheet.loc[sheet["Mean"].eq(means.OVERALL_ROW)].iloc[0]


def assert_close(row, expected):
    for field, key in zip(FIELDS, ("mean", "se", "df", "low", "high")):
        actual = row[field]
        wanted = expected[key]
        if abs(actual - wanted) > 1e-10:
            raise AssertionError(f"{field}: {actual} != {wanted}")


class OracleTests(unittest.TestCase):
    def test_cells_marginals_and_overall_match_the_oracle(self):
        frame = oracle_frame()
        calls = {"n": 0}
        real = engine._factorial_anova_components

        def wrapped(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        with mock.patch("analisi.stats._factorial_anova_components", wrapped):
            data, design, beta, error, df = fit(frame, ["A", "B"], 2)
        self.assertEqual(calls["n"], 1)
        model = ["A", "B"]
        cells = means.tables(means.check_options(
            {means.ENABLED: True, means.FACTORS: ["A", "B"], means.OVERALL: True,
             means.CONFIDENCE: ORACLE["confidence"]}, model), model, data, design, beta, error, df)[means.SHEET]
        by_a = means.tables(means.check_options(
            {means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: 0.95}, model),
            model, data, design, beta, error, df)[means.SHEET]
        by_b = means.tables(means.check_options(
            {means.ENABLED: True, means.FACTORS: ["B"], means.CONFIDENCE: 0.95}, model),
            model, data, design, beta, error, df)[means.SHEET]
        expected = ORACLE["expected"]
        for label, levels in (("A0 B0", {"A": "A0", "B": "B0"}), ("A0 B1", {"A": "A0", "B": "B1"}),
                              ("A1 B0", {"A": "A1", "B": "B0"}), ("A1 B1", {"A": "A1", "B": "B1"})):
            assert_close(combination(cells, **levels), expected[label])
        assert_close(overall(cells), expected["Globale"])
        for level in ("A0", "A1"):
            assert_close(combination(by_a, A=level), expected[level])
        for level in ("B0", "B1"):
            assert_close(combination(by_b, B=level), expected[level])
        self.assertTrue((cells["Weighting"] == means.WEIGHTING_TEXT).all())
        self.assertTrue((cells["Status"] == "OK").all())
        self.assertTrue((cells["Reason"] == "").all())
        self.assertEqual(int(cells["df"].iloc[0]), 7)

    def test_unbalanced_marginal_is_not_the_raw_mean(self):
        frame = oracle_frame()
        sheet = sheet_of(frame, ["A", "B"], marginal=["A"])
        raw = frame.loc[frame.A == "A0", "Y"].mean()
        estimate = combination(sheet, A="A0")["Estimate"]
        self.assertAlmostEqual(estimate, 5.0, delta=1e-10)
        self.assertGreater(abs(estimate - raw), 0.5)

    def test_sums_of_squares_do_not_change_the_means(self):
        frame = oracle_frame()
        sheets = [sheet_of(frame, ["A", "B"], marginal=["A", "B"], overall=True, sums_of_squares=kind)
                  for kind in ("Type I", "Type II", "Type III")]
        for other in sheets[1:]:
            assert_frame_equal(other, sheets[0])


def additive_oracle(frame, confidence=0.95):
    """Treatment-coded additive least squares, independent of the ANOVA design matrix.

    Predictions cover every cell of the reference grid, including a cell with no rows. Each reported
    mean averages those predictions with equal weight. The variance is MSE × L (X′X)⁺ L′.
    """
    a_levels = sorted(frame["A"].astype(str).unique())
    b_levels = sorted(frame["B"].astype(str).unique())
    a_code = {level: index for index, level in enumerate(a_levels)}
    b_code = {level: index for index, level in enumerate(b_levels)}
    rows = []
    for record in frame.itertuples(index=False):
        a, b = str(record.A), str(record.B)
        line = [0.0] * (1 + len(a_levels) - 1 + len(b_levels) - 1)
        line[0] = 1.0
        if a_code[a]:
            line[a_code[a]] = 1.0
        if b_code[b]:
            line[len(a_levels) - 1 + b_code[b]] = 1.0
        rows.append(line)
    x = np.asarray(rows, dtype=float)
    y = frame["Y"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    df = len(y) - np.linalg.matrix_rank(x)
    mse = float(np.sum((y - fitted) ** 2) / df)
    covariance = mse * np.linalg.pinv(x.T @ x, hermitian=True)
    critical = stats.t.ppf(0.5 + confidence / 2, df)

    def row_of(a, b):
        line = [0.0] * x.shape[1]
        line[0] = 1.0
        if a_code[a]:
            line[a_code[a]] = 1.0
        if b_code[b]:
            line[len(a_levels) - 1 + b_code[b]] = 1.0
        return np.asarray(line)

    cells = {(a, b): row_of(a, b) for a in a_levels for b in b_levels}

    def summarise(vectors):
        coefficients = np.mean(np.vstack(vectors), axis=0)
        estimate = float(coefficients @ beta)
        se = float(np.sqrt(coefficients @ covariance @ coefficients))
        return {"mean": estimate, "se": se, "df": df, "low": estimate - critical * se,
                "high": estimate + critical * se}

    report = {f"{a} {b}": summarise([cells[a, b]]) for a, b in cells}
    for a in a_levels:
        report[a] = summarise([cells[a, b] for b in b_levels])
    for b in b_levels:
        report[b] = summarise([cells[a, b] for a in a_levels])
    report["Globale"] = summarise(list(cells.values()))
    return report


class MissingCellTests(unittest.TestCase):
    def frame(self):
        rows = [("a0", "b0", 1), ("a0", "b0", 3), ("a0", "b1", 5), ("a0", "b1", 7),
                ("a1", "b0", 4), ("a1", "b0", 6), ("a1", "b0", 8)]
        return pd.DataFrame(rows, columns=["A", "B", "Y"])

    def test_saturated_model_still_refuses_the_rank_deficient_fit(self):
        with self.assertRaises(ValueError) as raised:
            fit(self.frame(), ["A", "B"], 2)
        self.assertIn("rank deficient", str(raised.exception).lower())

    def test_additive_model_estimates_the_missing_cell(self):
        frame = self.frame()
        wanted = additive_oracle(frame)
        data, design, beta, error, df = fit(frame, ["A", "B"], 1)
        model = ["A", "B"]
        cells = means.tables(means.check_options(
            {means.ENABLED: True, means.FACTORS: ["A", "B"], means.OVERALL: True}, model),
            model, data, design, beta, error, df)[means.SHEET]
        by_a = means.tables(means.check_options(
            {means.ENABLED: True, means.FACTORS: ["A"]}, model), model, data, design, beta, error, df)[means.SHEET]
        for label, levels in (("a0 b0", {"A": "a0", "B": "b0"}), ("a0 b1", {"A": "a0", "B": "b1"}),
                              ("a1 b0", {"A": "a1", "B": "b0"}), ("a1 b1", {"A": "a1", "B": "b1"})):
            assert_close(combination(cells, **levels), wanted[label])
        assert_close(overall(cells), wanted["Globale"])
        assert_close(combination(by_a, A="a1"), wanted["a1"])
        self.assertEqual(combination(cells, A="a1", B="b1")["Status"], "OK")
        # The missing cell is not the average of the observed cells of A1.
        self.assertGreater(abs(combination(cells, A="a1", B="b1")["Estimate"] - frame.loc[frame.A == "a1", "Y"].mean()),
                           0.5)

    def test_selected_main_effects_match_the_additive_hierarchy(self):
        frame = self.frame()
        hierarchy = sheet_of(frame, ["A", "B"], order=1, marginal=["A", "B"], overall=True)
        selected = sheet_of(frame, ["A", "B"], marginal=["A", "B"], overall=True, terms=[["A"], ["B"]])
        assert_frame_equal(selected, hierarchy)


class EstimabilityTests(unittest.TestCase):
    def test_a_mean_outside_the_row_space_is_empty_and_says_why(self):
        design = np.array([[1, 1, 0], [1, 1, 0], [1, 0, 1], [1, 0, 1.]])
        beta = np.array([1., 2, 3])
        rows = np.array([[0, 1, 0.], [0, 1, -1.]])
        empty, ok = means.linear_means(rows, design, beta, 2.0, 2, 0.95)
        self.assertEqual(empty["Status"], "Not estimable")
        self.assertEqual(empty["Reason"], means.REASON_NOT_ESTIMABLE)
        for field in ("Estimate", "SE", "df", "CI low", "CI high"):
            self.assertTrue(np.isnan(empty[field]), field)
        self.assertEqual(empty["Weighting"], means.WEIGHTING_TEXT)
        self.assertEqual(ok["Status"], "OK")
        self.assertEqual(ok["Reason"], "")
        self.assertAlmostEqual(ok["SE"], 1.0, delta=1e-12)
        self.assertEqual(ok["df"], 2)


class RequestTests(unittest.TestCase):
    def options(self, **extra):
        return {means.ENABLED: True, means.FACTORS: ["A"], means.OVERALL: False, means.CONFIDENCE: 0.95, **extra}

    def test_absent_or_false_reads_nothing(self):
        self.assertIsNone(means.check_options({}, ["A"]))
        self.assertIsNone(means.check_options({means.ENABLED: False, means.FACTORS: ["nope"], means.CONFIDENCE: 5}, ["A"]))
        self.assertFalse(means.active({means.FACTORS: ["A"]}))

    def test_invalid_requests_name_the_field(self):
        cases = [
            ({means.ENABLED: "yes"}, means.ENABLED),
            ({means.ENABLED: True, means.FACTORS: "A"}, means.FACTORS),
            ({means.ENABLED: True, means.FACTORS: ["A", "A"]}, means.FACTORS),
            ({means.ENABLED: True, means.FACTORS: ["C"]}, means.FACTORS),
            ({means.ENABLED: True, means.FACTORS: [], means.OVERALL: False}, means.FACTORS),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.OVERALL: "yes"}, means.OVERALL),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: 0}, means.CONFIDENCE),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: 1}, means.CONFIDENCE),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: 95}, means.CONFIDENCE),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: float("nan")}, means.CONFIDENCE),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: True}, means.CONFIDENCE),
            ({means.ENABLED: True, means.FACTORS: ["A"], means.CONFIDENCE: "0.95"}, means.CONFIDENCE),
        ]
        for options, field in cases:
            with self.subTest(options=options):
                with self.assertRaises(FieldError) as raised:
                    means.check_options(options, ["A", "B"])
                self.assertEqual(raised.exception.field, field)

    def test_overall_mean_alone_is_allowed(self):
        factors, include, confidence = means.check_options(
            {means.ENABLED: True, means.OVERALL: True}, ["A"])
        self.assertEqual((factors, include, confidence), ([], True, 0.95))

    def test_italian_errors_use_the_sentences_the_engine_raises(self):
        import string
        from analisi.i18n import _EN, set_language
        sample = {"factor": "“A”", "text": "“1”", "cells": 3, "limit": 4096}
        set_language("it")
        try:
            for key, english in means.ERRORS.items():
                self.assertEqual(_EN[f"anova.means.error.{key}"], english)
                names = [name for _, name, _, _ in string.Formatter().parse(english) if name]
                text = english.format(**{name: sample[name] for name in names})
                italian = means.localized(text)
                self.assertNotEqual(italian, text)
                self.assertNotIn("{", italian)
        finally:
            set_language("en")

    def test_special_characters_stay_literal(self):
        levels, doses = ['B |', '100%', 'µ "x"'], ["low", "high"]
        rows = [(level, dose, value) for level in levels for dose in doses for value in (1.0, 3.0)]
        frame = pd.DataFrame(rows, columns=["A & B", "Dose", "Y"])
        sheet = sheet_of(frame, ["A & B", "Dose"], marginal=["A & B", "Dose"])
        self.assertEqual(sheet.columns.tolist()[:2], ["A & B", "Dose"])
        self.assertEqual(sheet["A & B"].tolist(), ['100%', '100%', 'B |', 'B |', 'µ "x"', 'µ "x"'])
        self.assertEqual(sheet["Dose"].tolist(), ["high", "low"] * 3)
        self.assertAlmostEqual(combination(sheet, **{"A & B": 'µ "x"', "Dose": "high"})["Estimate"], 2, delta=1e-10)

    def test_a_factor_named_like_a_column_is_disambiguated(self):
        frame = oracle_frame().rename(columns={"A": "Estimate", "B": "Mean"})
        renamed = frame.rename(columns={"Estimate": "Estimate"})
        data, design, beta, error, df = fit(renamed, ["Estimate", "Mean"], 2)
        request = means.check_options({means.ENABLED: True, means.FACTORS: ["Mean", "Estimate"],
                                       means.OVERALL: True}, ["Estimate", "Mean"])
        sheet = means.tables(request, ["Estimate", "Mean"], data, design, beta, error, df)[means.SHEET]
        self.assertEqual(sheet.columns.tolist()[:3], ["Mean", "Mean (factor)", "Estimate (factor)"])
        self.assertAlmostEqual(combination(sheet, **{"Mean (factor)": "B0", "Estimate (factor)": "A0"})["Estimate"],
                               2, delta=1e-10)

    def test_complete_rows_drop_a_missing_response_and_a_lost_level(self):
        frame = oracle_frame()
        frame.loc[0, "Y"] = np.nan  # one A0 B0 response is not used
        kept = sheet_of(frame.dropna(), ["A", "B"], marginal=["A", "B"])
        dropped = sheet_of(frame, ["A", "B"], marginal=["A", "B"])
        assert_frame_equal(dropped, kept)
        # B2 is absent from the complete rows, so the sheet does not invent that level.
        rows = [(a, b, y) for a in ("A0", "A1") for b, values in (("B0", (1, 2)), ("B1", (3, 4)), ("B2", (5, 6)))
                for y in values]
        gone = pd.DataFrame(rows, columns=["A", "B", "Y"])
        gone.loc[gone.B == "B2", "Y"] = np.nan
        self.assertEqual(sheet_of(gone, ["A", "B"], marginal=["B"])["B"].tolist(), ["B0", "B1"])

    def test_colliding_categories_are_an_error_only_when_the_means_are_on(self):
        frame = oracle_frame()
        frame["B"] = frame["B"].astype(object)
        frame.loc[frame.B == "B0", "B"] = 1
        frame.loc[frame.index[:2], "B"] = "1"
        means.check_data(None, frame, "Y", ["A", "B"])
        request = means.check_options({means.ENABLED: True, means.FACTORS: ["A"]}, ["A", "B"])
        with self.assertRaises(FieldError) as raised:
            means.check_data(request, frame, "Y", ["A", "B"])
        self.assertEqual(raised.exception.field, means.FACTORS)
        self.assertIn("“1”", str(raised.exception))

    def test_the_reference_grid_is_limited_before_any_coefficient_is_built(self):
        width, height = 64, 65
        self.assertGreater(width * height, means.MAX_CELLS)
        frame = pd.DataFrame({"A": np.repeat(np.arange(width), height).astype(str),
                              "B": np.tile(np.arange(height), width).astype(str),
                              "Y": 1.0})
        request = means.check_options({means.ENABLED: True, means.FACTORS: ["A"]}, ["A", "B"])
        with mock.patch("analisi.stats._anova_model") as fitted:
            with self.assertRaises(FieldError) as raised:
                means.check_data(request, frame, "Y", ["A", "B"])
        fitted.assert_not_called()
        self.assertEqual(raised.exception.field, means.FACTORS)
        self.assertIn(str(means.MAX_CELLS), str(raised.exception))
        self.assertIn(str(width * height), str(raised.exception))


class AnalysisTests(unittest.TestCase):
    def legacy(self, **extra):
        return {"Response": "Y", "Factors": ["A", "B"], "Interaction order": 2, **extra}

    def asked(self, **extra):
        return {means.ENABLED: True, means.FACTORS: ["A", "B"], means.OVERALL: True,
                means.CONFIDENCE: 0.95, **extra}

    def test_the_option_is_in_the_catalog_and_off_for_an_old_recipe(self):
        catalog = METHODS[METHOD]
        for key in means.KEYS:
            self.assertIn(key, catalog)
        frame = oracle_frame()
        before = analyse(METHOD, frame, self.legacy())
        after = analyse(METHOD, frame, {**self.legacy(), means.FACTORS: ["not a factor"], means.CONFIDENCE: 9,
                                        means.OVERALL: True})
        explicit = analyse(METHOD, frame, {**self.legacy(), means.ENABLED: False, means.FACTORS: ["A"]})
        self.assertEqual(list(before.tables), list(after.tables))
        self.assertEqual(list(before.tables), list(explicit.tables))
        for name in before.tables:
            assert_frame_equal(after.tables[name], before.tables[name])
            assert_frame_equal(explicit.tables[name], before.tables[name])
        self.assertNotIn(means.SHEET, before.tables)

    def test_one_fit_when_comparisons_are_off_and_no_extra_fit_when_they_are_on(self):
        frame = oracle_frame()
        real = engine._anova_model
        calls = {"n": 0}

        def wrapped(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        def count(options):
            calls["n"] = 0
            with mock.patch("analisi.stats._anova_model", wrapped), mock.patch("analisi.advanced._anova_model", wrapped):
                result = analyse(METHOD, frame, options)
            return calls["n"], result

        plain, with_means = count(self.legacy()), count({**self.legacy(), **self.asked()})
        self.assertEqual(plain[0], 1)
        self.assertEqual(with_means[0], 1)
        self.assertIn(means.SHEET, with_means[1].tables)
        compared = {**self.legacy(), "Compare marginal means by": "A"}
        without, with_both = count(compared), count({**compared, **self.asked()})
        self.assertEqual(without[0], with_both[0])
        self.assertGreater(without[0], 1)
        for name in without[1].tables:
            assert_frame_equal(with_both[1].tables[name], without[1].tables[name])

    def test_analyse_reproduces_the_oracle(self):
        result = analyse(METHOD, oracle_frame(), {**self.legacy(), **self.asked()})
        sheet = result.tables[means.SHEET]
        assert_close(combination(sheet, A="A0", B="B0"), ORACLE["expected"]["A0 B0"])
        assert_close(overall(sheet), ORACLE["expected"]["Globale"])

    def test_a_factor_outside_the_selected_terms_is_refused_before_the_fit(self):
        frame = oracle_frame()
        frame["C"] = np.where(frame.index % 2, "c0", "c1")
        options = {"Response": "Y", "Factors": ["A", "B", "C"], "Term selection": "Selected terms",
                   "Model terms": [["A"], ["B"]], **self.asked()}
        options[means.FACTORS] = ["C"]
        with mock.patch("analisi.stats._anova_model") as fitted:
            with self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame, options)
        fitted.assert_not_called()
        self.assertEqual(raised.exception.field, means.FACTORS)
        self.assertIn("“C”", str(raised.exception))

    def test_invalid_confidence_and_a_wide_grid_do_not_fit(self):
        frame = oracle_frame()
        with mock.patch("analisi.stats._anova_model") as fitted:
            with self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame, {**self.legacy(), **self.asked(), means.CONFIDENCE: 0})
        fitted.assert_not_called()
        self.assertEqual(raised.exception.field, means.CONFIDENCE)
        wide = pd.DataFrame({"A": np.repeat(np.arange(64), 65).astype(str),
                             "B": np.tile(np.arange(65), 64).astype(str), "Y": 1.0})
        with mock.patch("analisi.stats._anova_model") as fitted:
            with self.assertRaises(FieldError) as raised:
                analyse(METHOD, wide, {"Response": "Y", "Factors": ["A", "B"], "Interaction order": 1,
                                      **self.asked()})
        fitted.assert_not_called()
        self.assertEqual(raised.exception.field, means.FACTORS)


if __name__ == "__main__":
    unittest.main()
