"""Replicate lack-of-fit test for multiple linear regression.

The reference sheet is the additive model on ``tests/data/replicate-lack-of-fit/repliche.csv``.
``riferimento.R`` compares that model with a saturated model, one mean per predictor combination.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analisi.data import Dataset, load_project, save_project
from analisi.i18n import _EN, _IT, set_language, tr
from analisi.ols_diagnostics import (
    LACK_OF_FIT_SHEET, NOTE_AVAILABLE, NOTE_CLAMPED, NOTE_NEGATIVE, NOTE_NO_DEGREES, NOTE_NO_REPLICATES,
    NOTE_NONFINITE, NOTE_PREDICTIONS, NOTE_RESIDUALS, NOTE_WEIGHTS, NOTE_ZERO_BOTH, NOTE_ZERO_PURE,
    REPLICATE_LACK_OF_FIT, _NOTE_KEYS, build_lack_of_fit_table, show_component, show_note,
)
from analisi.processing import FieldError
from analisi.workbench import analyse

METHOD = "Multiple regression"
ROOT = Path(__file__).resolve().parents[1] / "tests" / "data" / "replicate-lack-of-fit"
REFERENCE_P = 0.01613008990009255


def reference_frame():
    return pd.read_csv(ROOT / "repliche.csv")


def fit(frame, **extra):
    options = {"Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
               "Family": "Linear", REPLICATE_LACK_OF_FIT: True, **extra}
    return analyse(METHOD, frame, options)


def sheet_of(frame, **extra):
    return fit(frame, **extra).tables[LACK_OF_FIT_SHEET]


class ReferenceTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_reference_numbers(self):
        sheet = sheet_of(reference_frame())
        residual, pure, lack = sheet.loc["Residual"], sheet.loc["Pure error"], sheet.loc["Lack of fit"]
        self.assertEqual(int(residual["N"]), 8)
        self.assertEqual(int(residual["Distinct combinations"]), 4)
        self.assertEqual(int(residual["Rank"]), 3)
        self.assertEqual(int(residual["Replicate groups"]), 4)
        self.assertEqual([int(row["df"]) for _, row in sheet.iterrows()], [5, 4, 1])
        # The sums are the integers 40, 8 and 32. One ulp of residual roundoff still displays as those integers.
        np.testing.assert_allclose(sheet["SS"].to_numpy(dtype=float), [40, 8, 32], rtol=0, atol=1e-8)
        np.testing.assert_allclose(sheet["MS"].to_numpy(dtype=float), [8, 2, 32], rtol=0, atol=1e-8)
        self.assertEqual([f"{value:.10g}" for value in sheet["SS"]], ["40", "8", "32"])
        self.assertEqual(f"{float(lack['F']):.10g}", "16")
        self.assertTrue(pd.isna(residual["F"]) and pd.isna(pure["F"]))
        self.assertTrue(np.isclose(float(lack["F"]), 16, rtol=0, atol=1e-8))
        self.assertTrue(np.isclose(float(lack["p"]), float(stats.f.sf(16, 1, 4)), rtol=0, atol=1e-12))
        self.assertTrue(np.isclose(float(lack["p"]), REFERENCE_P, rtol=0, atol=1e-12))
        self.assertEqual(lack["Note"], NOTE_AVAILABLE)
        self.assertEqual(residual["Note"], "")
        # Rows that share only X1 stay in different groups: U would be 2 if X2 were ignored.
        self.assertEqual(int(residual["Distinct combinations"]), 4)

    def test_categorical_labels_match_the_numeric_fit(self):
        frame = reference_frame()
        frame["X2"] = frame["X2"].map({0: "low", 1: "high"})
        numeric = sheet_of(reference_frame())
        categorical = sheet_of(frame, **{"Categorical predictors": ["X2"]})
        for column in ("SS", "MS", "F", "p"):
            np.testing.assert_allclose(categorical[column].to_numpy(dtype=float),
                                       numeric[column].to_numpy(dtype=float), rtol=0, atol=1e-8, equal_nan=True)
        self.assertEqual(categorical["df"].tolist(), numeric["df"].tolist())
        self.assertEqual(int(categorical.loc["Residual", "Distinct combinations"]), 4)

    def test_shuffled_rows_keep_the_sums(self):
        shuffled = reference_frame().sample(frac=1, random_state=7).reset_index(drop=True)
        original, moved = sheet_of(reference_frame()), sheet_of(shuffled)
        np.testing.assert_allclose(moved["SS"].to_numpy(dtype=float), original["SS"].to_numpy(dtype=float))
        self.assertEqual(moved["df"].tolist(), original["df"].tolist())

    def test_excluded_measurement_matches_an_independent_fit(self):
        data = Dataset(reference_frame())
        data.excluded.add((7, 2))  # the last Y, source row 8
        remaining = data.frame(mask_excluded=True).dropna()
        y = remaining["Y"].to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(y)), remaining["X1"].to_numpy(dtype=float),
                                  remaining["X2"].to_numpy(dtype=float)])
        fitted = design @ np.linalg.lstsq(design, y, rcond=None)[0]
        residual_ss = float((y - fitted) @ (y - fitted))
        groups = {}
        for x1, x2, value in zip(remaining["X1"], remaining["X2"], y, strict=True):
            groups.setdefault((float(x1), float(x2)), []).append(float(value))
        pure = 0.0
        for values in groups.values():
            centre = sum(values) / len(values)
            pure += sum((value - centre) ** 2 for value in values)
        distinct, rank = len(groups), int(np.linalg.matrix_rank(design))
        lack = residual_ss - pure
        df_pure, df_lack = len(y) - distinct, distinct - rank
        expected_f = (lack / df_lack) / (pure / df_pure)
        sheet = sheet_of(data.frame(mask_excluded=True))
        self.assertEqual(int(sheet.loc["Residual", "N"]), len(y))
        self.assertEqual(int(sheet.loc["Residual", "Distinct combinations"]), distinct)
        self.assertEqual(int(sheet.loc["Residual", "Rank"]), rank)
        np.testing.assert_allclose(sheet["SS"].to_numpy(dtype=float), [residual_ss, pure, lack], rtol=0, atol=1e-8)
        self.assertEqual([int(value) for value in sheet["df"]], [len(y) - rank, df_pure, df_lack])
        self.assertTrue(np.isclose(float(sheet.loc["Lack of fit", "F"]), expected_f, rtol=0, atol=1e-8))
        self.assertTrue(np.isclose(float(sheet.loc["Lack of fit", "p"]),
                                   float(stats.f.sf(expected_f, df_lack, df_pure)), rtol=0, atol=1e-10))

    def test_minus_zero_shares_a_combination(self):
        frame = pd.DataFrame({"X1": [0.0, -0.0, 1.0, 1.0, 2.0, 2.0],
                              "X2": [0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
                              "Y": [1.0, 3.0, 4.0, 6.0, 5.0, 7.0]})
        sheet = sheet_of(frame)
        self.assertEqual(int(sheet.loc["Residual", "Distinct combinations"]), 3)
        self.assertEqual(int(sheet.loc["Residual", "Replicate groups"]), 3)


class BoundaryTests(unittest.TestCase):
    def test_no_replicates_blanks_f_and_p(self):
        frame = pd.DataFrame({"X1": [0, 1, 2, 3, 4.], "X2": [0, 1, 0, 1, 0.], "Y": [1, 2, 3, 4, 6.]})
        sheet = sheet_of(frame)
        self.assertEqual(int(sheet.loc["Residual", "Replicate groups"]), 0)
        self.assertEqual(int(sheet.loc["Pure error", "df"]), 0)
        self.assertEqual(sheet.loc["Lack of fit", "Note"], NOTE_NO_REPLICATES)
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "F"]))
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "p"]))
        self.assertTrue(np.isfinite(sheet["SS"]).all())

    def test_no_numerator_degrees_of_freedom(self):
        frame = pd.DataFrame({"X1": [0, 0, 0, 1, 1, 1.], "X2": [0, 0, 0, 0, 0, 0.], "Y": [1, 2, 3, 4, 6, 8.]})
        options = {"Response": "Y", "Predictors": ["X1"], "Categorical predictors": [],
                   "Family": "Linear", REPLICATE_LACK_OF_FIT: True}
        sheet = analyse(METHOD, frame, options).tables[LACK_OF_FIT_SHEET]
        self.assertEqual(int(sheet.loc["Lack of fit", "df"]), 0)
        self.assertGreater(int(sheet.loc["Pure error", "df"]), 0)
        self.assertEqual(sheet.loc["Lack of fit", "Note"], NOTE_NO_DEGREES)
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "F"]))
        self.assertTrue(np.isfinite(float(sheet.loc["Lack of fit", "SS"])))

    def test_zero_pure_error_with_a_positive_lack_of_fit(self):
        frame = pd.DataFrame({"X1": [0, 0, 0, 0, 1, 1, 1, 1.], "X2": [0, 0, 1, 1, 0, 0, 1, 1.],
                              "Y": [0, 0, 0, 0, 0, 0, 4, 4.]})
        sheet = sheet_of(frame)
        self.assertEqual(float(sheet.loc["Pure error", "SS"]), 0.0)
        self.assertGreater(float(sheet.loc["Lack of fit", "SS"]), 0.0)
        self.assertEqual(sheet.loc["Lack of fit", "Note"], NOTE_ZERO_PURE)
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "F"]))
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "p"]))

    def test_both_sums_zero(self):
        observed = np.array([0, 0, 1, 1, 2, 2, 3, 3], dtype=float)
        predictors = pd.DataFrame({"A": [0, 0, 1, 1, 0, 0, 1, 1.], "B": [0, 0, 0, 0, 1, 1, 1, 1.]})
        sheet = build_lack_of_fit_table(observed, observed, np.zeros(8), predictors, [], 2)
        self.assertEqual(sheet["SS"].tolist(), [0.0, 0.0, 0.0])
        self.assertEqual(sheet.loc["Lack of fit", "Note"], NOTE_ZERO_BOTH)
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "F"]))

    def test_tiny_negative_is_clamped_and_a_larger_one_is_not(self):
        observed = np.array([0.0, 1.0, 10.0, 12.0])
        predicted = np.array([0.5, 0.5, 11.0, 11.0])
        true = observed - predicted
        predictors = pd.DataFrame({"X": [0.0, 0.0, 1.0, 1.0]})
        eps = np.finfo(float).eps
        clamped = build_lack_of_fit_table(observed, predicted, true - np.sign(true) * eps, predictors, [], 1)
        self.assertEqual(float(clamped.loc["Lack of fit", "SS"]), 0.0)
        self.assertEqual(float(clamped.loc["Lack of fit", "F"]), 0.0)
        self.assertEqual(float(clamped.loc["Lack of fit", "p"]), 1.0)
        self.assertEqual(clamped.loc["Lack of fit", "Note"], NOTE_CLAMPED)
        rejected = build_lack_of_fit_table(observed, predicted, true - np.sign(true) * (100 * eps), predictors, [], 1)
        self.assertTrue(pd.isna(rejected.loc["Lack of fit", "SS"]))
        self.assertTrue(pd.isna(rejected.loc["Lack of fit", "F"]))
        self.assertTrue(pd.isna(rejected.loc["Lack of fit", "p"]))
        self.assertEqual(rejected.loc["Lack of fit", "Note"], NOTE_NEGATIVE)
        self.assertTrue(np.isfinite(rejected.loc["Residual", "SS"]))
        self.assertTrue(np.isfinite(rejected.loc["Pure error", "SS"]))
        # The clamp is not mentioned when there is no numerator degree of freedom to report.
        one_group = build_lack_of_fit_table(np.array([0.0, 1.0]), np.array([0.5, 0.5]),
                                            np.array([-0.5, 0.5]) - eps, pd.DataFrame({"X": [0.0, 0.0]}), [], 1)
        self.assertEqual(one_group.loc["Lack of fit", "Note"], NOTE_NO_DEGREES)
        self.assertNotIn("set to zero", one_group.loc["Lack of fit", "Note"])

    def test_inconsistent_predictions_or_residuals_or_nonfinite_values(self):
        observed = np.array([0.0, 1.0])
        predictors = pd.DataFrame({"X": [0.0, 0.0]})
        predictions = build_lack_of_fit_table(observed, np.array([0.0, 1.0]), observed - np.array([0.0, 1.0]),
                                              predictors, [], 1)
        self.assertEqual(predictions.loc["Lack of fit", "Note"], NOTE_PREDICTIONS)
        self.assertTrue(pd.isna(predictions.loc["Lack of fit", "SS"]))
        self.assertTrue(np.isfinite(predictions.loc["Residual", "SS"]))
        residuals = build_lack_of_fit_table(observed, np.array([0.5, 0.5]), np.array([5.0, 5.0]), predictors, [], 1)
        self.assertEqual(residuals.loc["Lack of fit", "Note"], NOTE_RESIDUALS)
        self.assertTrue(residuals["SS"].isna().all())
        missing = build_lack_of_fit_table(np.array([1.0, np.nan]), np.array([0.5, 0.5]), np.array([0.5, np.nan]),
                                          predictors, [], 1)
        self.assertEqual(missing.loc["Residual", "Note"], NOTE_NONFINITE)
        self.assertTrue(pd.isna(missing.loc["Lack of fit", "F"]))

    def test_weights_explain_why_the_test_is_absent(self):
        weighed = fit(reference_frame(), **{"Gaussian weighting": "1/abs(Y)"})
        self.assertIn("Coefficients", weighed.tables)
        self.assertEqual(list(weighed.tables)[-1], LACK_OF_FIT_SHEET)
        sheet = weighed.tables[LACK_OF_FIT_SHEET]
        self.assertEqual(int(sheet.loc["Residual", "N"]), 8)
        self.assertTrue(sheet["SS"].isna().all())
        self.assertTrue(pd.isna(sheet.loc["Lack of fit", "F"]))
        self.assertEqual(sheet.loc["Lack of fit", "Note"], NOTE_WEIGHTS)
        plain = analyse(METHOD, reference_frame(), {"Response": "Y", "Predictors": ["X1", "X2"],
                                                    "Categorical predictors": [], "Family": "Linear",
                                                    "Gaussian weighting": "1/abs(Y)"})
        held = fit(reference_frame(), **{"Gaussian weighting": "1/abs(Y)", REPLICATE_LACK_OF_FIT: False})
        self.assertEqual(list(plain.tables), list(held.tables))
        self.assertNotIn(LACK_OF_FIT_SHEET, held.tables)
        for name in plain.tables:
            pd.testing.assert_frame_equal(plain.tables[name], held.tables[name])

    def test_off_and_missing_leave_the_other_sheets_unchanged(self):
        frame = reference_frame()
        base = {"Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [], "Family": "Linear",
                "Linear diagnostics": True}
        missing = analyse(METHOD, frame, dict(base))
        off = analyse(METHOD, frame, {**base, REPLICATE_LACK_OF_FIT: False})
        on = analyse(METHOD, frame, {**base, REPLICATE_LACK_OF_FIT: True})
        self.assertEqual(list(missing.tables), list(off.tables))
        self.assertEqual(list(on.tables)[:-1], list(off.tables))
        self.assertEqual(list(on.tables)[-1], LACK_OF_FIT_SHEET)
        for name in off.tables:
            pd.testing.assert_frame_equal(off.tables[name], on.tables[name])
            pd.testing.assert_frame_equal(missing.tables[name], off.tables[name])

    def test_other_families_ignore_the_flag_even_when_it_is_invalid(self):
        logistic = pd.DataFrame({"X1": [0, 1, 2, 3, 4, 5, 6, 7.], "X2": [0, 0, 1, 1, 0, 0, 1, 1.],
                                 "Y": [0, 0, 1, 0, 1, 1, 0, 1]})
        poisson = pd.DataFrame({"X1": [0, 1, 2, 3, 4, 5.], "X2": [1, 1, 1, 2, 2, 2.], "Y": [0, 1, 1, 3, 4, 7]})
        for family, frame in (("Logistic", logistic), ("Poisson", poisson)):
            plain = {"Family": family, "Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": []}
            without = analyse(METHOD, frame, plain)
            with_flag = analyse(METHOD, frame, {**plain, REPLICATE_LACK_OF_FIT: "nope"})
            self.assertEqual(list(without.tables), list(with_flag.tables), family)
            self.assertNotIn(LACK_OF_FIT_SHEET, with_flag.tables)
            for name in without.tables:
                pd.testing.assert_frame_equal(without.tables[name], with_flag.tables[name])

    def test_a_non_boolean_is_rejected_for_the_linear_family(self):
        with self.assertRaises(FieldError) as caught:
            fit(reference_frame(), **{REPLICATE_LACK_OF_FIT: "yes"})
        self.assertEqual(caught.exception.field, REPLICATE_LACK_OF_FIT)

    def test_notes_stay_english_in_the_engine_and_translate_for_display(self):
        for note, key in _NOTE_KEYS.items():
            self.assertEqual(_EN[key], note)
            self.assertNotEqual(_IT[key], note)
        self.assertEqual(show_note(NOTE_AVAILABLE), NOTE_AVAILABLE)
        self.assertEqual(show_component("Residual"), "Residual")
        set_language("it")
        self.assertEqual(show_component("Pure error"), "Errore puro")
        self.assertEqual(show_note(NOTE_WEIGHTS), tr("mlr.lof.note.weights"))
        self.assertIn("pesi", show_note(NOTE_WEIGHTS))

    def test_committed_example_reopens_to_the_reference(self):
        loaded = load_project(ROOT / "repliche.alab")["Repliche"]
        self.assertIs(loaded.analyses[0][1][REPLICATE_LACK_OF_FIT], True)
        sheet = analyse(METHOD, loaded.frame(), loaded.analyses[0][1]).tables[LACK_OF_FIT_SHEET]
        np.testing.assert_allclose(sheet["SS"].to_numpy(dtype=float), [40, 8, 32], rtol=0, atol=1e-8)
        self.assertTrue(np.isclose(float(sheet.loc["Lack of fit", "F"]), 16, rtol=0, atol=1e-8))
        self.assertTrue(np.isclose(float(sheet.loc["Lack of fit", "p"]), REFERENCE_P, rtol=0, atol=1e-12))

    def test_the_checkbox_survives_save_and_reopen(self):
        frame = reference_frame()
        options = {"Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
                   "Family": "Linear", REPLICATE_LACK_OF_FIT: True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "repliche.alab"
            save_project(path, {"Repliche": Dataset(frame, analyses=[(METHOD, options)])})
            loaded = load_project(path)["Repliche"]
        self.assertIs(loaded.analyses[0][1][REPLICATE_LACK_OF_FIT], True)
        reopened = analyse(METHOD, loaded.frame(), loaded.analyses[0][1]).tables[LACK_OF_FIT_SHEET]
        self.assertTrue(np.isclose(float(reopened.loc["Lack of fit", "F"]), 16, rtol=0, atol=1e-8))
        self.assertTrue(np.isclose(float(reopened.loc["Residual", "SS"]), 40, rtol=0, atol=1e-8))

    def test_fifty_thousand_rows_group_without_comparing_every_pair(self):
        groups, repeats = 1000, 50
        gid = np.repeat(np.arange(groups), repeats).astype(float)
        columns = {"G": gid, "S": np.sin(gid), "C": np.cos(gid), "Q": gid % 17,
                   "R": np.sin(gid / 7), "T": np.cos(gid / 3)}
        frame = pd.DataFrame(columns)
        frame["Y"] = gid + np.random.default_rng(0).normal(scale=0.1, size=len(gid))
        started = time.perf_counter()
        result = analyse(METHOD, frame, {"Response": "Y", "Predictors": list(columns), "Categorical predictors": [],
                                         "Family": "Linear", REPLICATE_LACK_OF_FIT: True})
        elapsed = time.perf_counter() - started
        fitted = result.tables["Fitted values"]
        rank = int(result.tables[LACK_OF_FIT_SHEET].loc["Residual", "Rank"])
        built = time.perf_counter()
        table = build_lack_of_fit_table(fitted["Observed"].to_numpy(dtype=float),
                                        fitted["Fitted"].to_numpy(dtype=float),
                                        fitted["Residual"].to_numpy(dtype=float),
                                        frame.loc[fitted.index, list(columns)], [], rank)
        builder = time.perf_counter() - built
        print(f"replicate lack-of-fit: analyse {elapsed:.3f}s, builder {builder:.3f}s, "
              f"N=50000, predictors={len(columns)}", file=sys.stderr)
        self.assertLess(builder, 1.0, f"builder took {builder:.3f}s")
        self.assertLess(elapsed, 5.0, f"analyse took {elapsed:.3f}s")
        self.assertEqual(int(table.loc["Residual", "N"]), 50_000)
        self.assertEqual(int(table.loc["Residual", "Distinct combinations"]), groups)
        self.assertEqual(int(result.tables[LACK_OF_FIT_SHEET].loc["Residual", "Distinct combinations"]), groups)


if __name__ == "__main__":
    unittest.main()
