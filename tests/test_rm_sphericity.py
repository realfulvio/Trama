"""Greenhouse–Geisser correction for one or two within-subject factors (Repeated measures ANOVA, 0.93)."""
import unittest
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.linalg import helmert

from analisi import inference, rm_sphericity
from analisi.field_error import FieldError
from analisi.workbench import METHODS, analyse

METHOD = "Repeated measures ANOVA"
VISIT, CONDITION = "Visit", "Condition"
# Synthetic 5 subjects × 3 visits × 3 conditions. Rows are subjects, columns are visit 1 condition 1, 2, 3, ...
MATRIX = np.array([
    [33, 37, 39, 39, 40, 46, 42, 46, 49],
    [37, 36, 43, 37, 44, 45, 45, 47, 51],
    [41, 44, 43, 44, 45, 48, 47, 47, 54],
    [29, 34, 37, 32, 42, 43, 41, 40, 47],
    [38, 43, 45, 40, 45, 50, 50, 51, 53]], dtype=float)
# Epsilons of the 3 × 3 matrix from an independent Helmert/Kronecker calculation (full precision).
EXPECTED_EPSILON = {VISIT: 0.9794908417346871, CONDITION: 0.5676776912068693, f"{VISIT}:{CONDITION}": 0.6465819122309571}


def long(matrix=MATRIX, levels=3):
    rows = []
    for subject, values in enumerate(matrix, start=1):
        for cell, value in enumerate(values):
            rows.append({"Subject": f"S{subject}", VISIT: f"Visit {cell // levels + 1}",
                         CONDITION: f"Condition {cell % levels + 1}", "Response": value})
    return pd.DataFrame(rows)


def options(correction="Geisser–Greenhouse", factors=(VISIT, CONDITION)):
    return {"Response": "Response", "Factors": list(factors), "Subject": "Subject", "Sphericity correction": correction}


def tables(frame, **kwargs):
    return analyse(METHOD, frame, options(**kwargs)).tables


def reference(frame, factors=(VISIT, CONDITION)):
    """Epsilon, F and p of every effect from Helmert bases and the covariance of the scores, never from the SS."""
    a_name, b_name = factors
    wide = frame.pivot_table(index="Subject", columns=[a_name, b_name], values="Response", sort=False)
    n, a, b = len(wide), frame[a_name].nunique(), frame[b_name].nunique()
    cube = wide.to_numpy().reshape(n, a, b)
    out = {}
    for term, kron in ((a_name, (helmert(a), np.ones((1, b)) / np.sqrt(b))),
                       (b_name, (np.ones((1, a)) / np.sqrt(a), helmert(b))),
                       (f"{a_name}:{b_name}", (helmert(a), helmert(b)))):
        basis = np.kron(*kron)
        scores = cube.reshape(n, -1) @ basis.T
        q = len(basis)
        covariance = np.atleast_2d(np.cov(scores, rowvar=False, ddof=1))
        eigenvalues = np.linalg.eigvalsh(covariance)
        epsilon = 1.0 if q == 1 else eigenvalues.sum() ** 2 / (q * np.square(eigenvalues).sum())
        statistic = (n - 1) * n * np.linalg.norm(scores.mean(axis=0)) ** 2 / ((n - 1) * np.trace(covariance))
        out[term] = (q, epsilon, statistic, stats.f.sf(statistic, q * epsilon, (n - 1) * q * epsilon),
                     stats.f.sf(statistic, q, (n - 1) * q))
    return out


class CorrectedTables(unittest.TestCase):
    def test_three_effects_match_an_independent_helmert_calculation(self):
        frame = long()
        result = tables(frame)
        self.assertEqual(list(result), ["ANOVA", "Sphericity"])
        self.assertEqual(list(result["Sphericity"]), rm_sphericity.COLUMNS)
        self.assertEqual(result["Sphericity"]["Term"].tolist(), [VISIT, CONDITION, f"{VISIT}:{CONDITION}"])
        for row, (term, (q, epsilon, statistic, p, plain)) in zip(result["Sphericity"].itertuples(index=False),
                                                                  reference(frame).items(), strict=True):
            with self.subTest(term=term):
                self.assertEqual(row[0], term)
                self.assertEqual(row[1], q)
                np.testing.assert_allclose([row[2], row[3], row[4], row[5], row[6], row[7]],
                                           [epsilon, statistic, q * epsilon, 4 * q * epsilon, p, plain], rtol=1e-10)
                self.assertAlmostEqual(row[2], EXPECTED_EPSILON[term], places=12)

    def test_the_three_epsilons_differ_and_stay_inside_their_limits(self):
        sphericity = tables(long())["Sphericity"].set_index("Term")
        epsilons = sphericity["GG ε"]
        self.assertEqual(len(set(epsilons.round(7))), 3)
        for term, dimension in sphericity["Contrast dimension"].items():
            self.assertTrue(1 / dimension <= epsilons[term] <= 1, term)

    def test_sums_of_squares_and_f_are_those_of_the_uncorrected_table(self):
        frame = long()
        plain, corrected = tables(frame, correction="None")["ANOVA"], tables(frame)["ANOVA"]
        self.assertEqual(list(plain.index), list(corrected.index))
        for column in ("SS", "df", "MS", "F"):
            pd.testing.assert_series_equal(plain[column], corrected[column], check_exact=True)
        self.assertNotIn("GG ε", plain)
        self.assertEqual(corrected["GG ε"].notna().tolist(), [False, True, False, True, False, True, False])

    def test_one_corrected_p_is_the_upper_tail_of_f_with_fractional_degrees_of_freedom(self):
        row = tables(long())["ANOVA"].loc[CONDITION]
        epsilon = EXPECTED_EPSILON[CONDITION]
        self.assertAlmostEqual(row["F df1"], 2 * epsilon, places=12)
        self.assertAlmostEqual(row["F df2"], 8 * epsilon, places=12)
        self.assertNotEqual(row["F df1"], round(row["F df1"]))
        self.assertAlmostEqual(row["p"], stats.f.sf(row["F"], 2 * epsilon, 8 * epsilon), places=15)
        self.assertGreater(row["p"], stats.f.sf(row["F"], 2, 8))

    def test_each_effect_uses_the_stratum_of_its_own_error(self):
        table = tables(long())["ANOVA"]
        for term, error in ((VISIT, 18.622222222222284), (CONDITION, 15.022222222222235),
                            (f"{VISIT}:{CONDITION}", 64.04444444444444)):
            self.assertAlmostEqual(table.loc[f"Subject:{term}", "SS"], error, places=10)

    def test_two_levels_give_epsilon_exactly_one(self):
        frame = long(MATRIX[:, [0, 1, 3, 4]], levels=2)
        frame[VISIT] = frame[VISIT].replace({"Visit 3": "Visit 2"})
        result = tables(frame)
        self.assertEqual(result["Sphericity"]["GG ε"].tolist(), [1.0, 1.0, 1.0])
        np.testing.assert_array_equal(result["Sphericity"]["Contrast dimension"], [1, 1, 1])
        pd.testing.assert_series_equal(result["Sphericity"]["p"], result["Sphericity"]["Uncorrected p"],
                                       check_names=False, check_exact=True)
        plain = tables(frame, correction="None")["ANOVA"]
        np.testing.assert_array_equal(result["ANOVA"]["p"].to_numpy(), plain["p"].to_numpy())

    def test_swapping_the_factors_swaps_the_conclusions_and_keeps_the_interaction(self):
        frame = long()
        straight = tables(frame)["Sphericity"].set_index("Term")
        swapped = tables(frame, factors=(CONDITION, VISIT))["Sphericity"].set_index("Term")
        self.assertEqual(list(swapped.index), [CONDITION, VISIT, f"{CONDITION}:{VISIT}"])
        pd.testing.assert_series_equal(swapped.loc[CONDITION], straight.loc[CONDITION])
        pd.testing.assert_series_equal(swapped.loc[VISIT], straight.loc[VISIT])
        np.testing.assert_allclose(swapped.loc[f"{CONDITION}:{VISIT}"].to_numpy(),
                                   straight.loc[f"{VISIT}:{CONDITION}"].to_numpy(), rtol=1e-12)

    def test_offsets_scale_and_row_order_do_not_change_the_correction(self):
        frame = long()
        plain = tables(frame)["Sphericity"].set_index("Term")
        shifted = frame.assign(Response=8.0 * frame["Response"] + frame["Subject"].map(
            {"S1": 1e6, "S2": -1e6, "S3": 2e6, "S4": -2e6, "S5": 5e5}))
        changed = tables(shifted.sample(frac=1, random_state=3))["Sphericity"].set_index("Term").reindex(plain.index)
        np.testing.assert_allclose(changed["GG ε"], plain["GG ε"], rtol=1e-9)
        np.testing.assert_allclose(changed["F"], plain["F"], rtol=1e-8)
        np.testing.assert_allclose(changed["p"], plain["p"], rtol=1e-7)

    def test_epsilon_does_not_depend_on_the_unit_of_the_response(self):
        base = tables(long())["Sphericity"]["GG ε"].to_numpy()
        for factor in (1e-100, 1e-3, 1e12, 1e100):
            with self.subTest(factor=factor), warnings.catch_warnings():
                warnings.simplefilter("error")
                scaled = tables(long().assign(Response=long()["Response"] * factor))["Sphericity"]
            np.testing.assert_allclose(scaled["GG ε"], base, rtol=1e-9)
            self.assertTrue(np.isfinite(scaled.select_dtypes("number").to_numpy()).all())

    def test_text_categories_and_numbers_keep_their_real_subject_level_pairs(self):
        frame = long()
        relabelled = frame.assign(Subject=frame["Subject"].map({f"S{i}": name for i, name in enumerate(
            ["Ana", "Bo", "Ça", "Dé", "Eli"], start=1)}),
            **{VISIT: frame[VISIT].map({"Visit 1": "10", "Visit 2": "9", "Visit 3": "1e1"})},
            **{CONDITION: frame[CONDITION].map({"Condition 1": 1, "Condition 2": 2, "Condition 3": 3})})
        np.testing.assert_allclose(tables(relabelled.sample(frac=1, random_state=9))["Sphericity"]["GG ε"],
                                   tables(frame)["Sphericity"]["GG ε"], rtol=1e-12)

    def test_two_subjects_still_give_an_epsilon_in_range(self):
        sphericity = tables(long(MATRIX[:2] + np.arange(9) ** 1.5))["Sphericity"]
        for epsilon, dimension in zip(sphericity["GG ε"], sphericity["Contrast dimension"], strict=True):
            self.assertTrue(1 / dimension <= epsilon <= 1)

    def test_a_large_design_stays_finite(self):
        rng = np.random.default_rng(93)
        n, a, b = 200, 8, 6
        cube = rng.normal(size=(n, a, b)) + np.arange(a)[None, :, None] * .3 + rng.normal(size=(n, 1, 1)) * 5
        frame = pd.DataFrame([(s, i, j, cube[s, i, j]) for s in range(n) for i in range(a) for j in range(b)],
                             columns=["Subject", VISIT, CONDITION, "Response"])
        result = tables(frame)
        self.assertEqual(result["Sphericity"]["Contrast dimension"].tolist(), [7, 5, 35])
        self.assertTrue(np.isfinite(result["Sphericity"].select_dtypes("number").to_numpy()).all())


class OneFactorAndLegacy(unittest.TestCase):
    @staticmethod
    def one_way():
        return long(MATRIX[:, [0, 3, 6]] + np.array([0, 1, 4]), levels=1).drop(columns=CONDITION)

    def test_the_new_choice_with_one_factor_is_the_historical_table(self):
        frame = self.one_way()
        old = analyse(METHOD, frame, options("Geisser–Greenhouse (one-way)", [VISIT])).tables
        new = analyse(METHOD, frame, options("Geisser–Greenhouse", [VISIT])).tables
        self.assertEqual(list(old), ["ANOVA"])
        self.assertEqual(list(new), ["ANOVA"])
        pd.testing.assert_frame_equal(new["ANOVA"], old["ANOVA"], check_exact=True)
        self.assertEqual(list(new["ANOVA"]), ["SS", "df", "MS", "F", "F df1", "F df2", "GG ε", "p"])

    def test_none_has_no_epsilon_column_and_no_sphericity_sheet(self):
        for frame, factors in ((long(), (VISIT, CONDITION)), (self.one_way(), (VISIT,))):
            result = tables(frame, correction="None", factors=factors)
            self.assertEqual(list(result), ["ANOVA"])
            self.assertNotIn("GG ε", result["ANOVA"])

    def test_the_historical_choice_keeps_its_one_factor_limit(self):
        with self.assertRaisesRegex(ValueError, "one within-subject factor"):
            inference.repeated_measures_anova(long(), "Response", [VISIT, CONDITION], "Subject",
                                              correction=rm_sphericity.GG_ONE_WAY)
        with self.assertRaises(FieldError) as error:
            tables(long(), correction="Geisser–Greenhouse (one-way)")
        self.assertEqual(error.exception.field, "Sphericity correction")

    def test_the_dialog_offers_the_historical_choice_only_for_a_recipe_that_has_it(self):
        offered = ("None", "Geisser–Greenhouse", "Huynh-Feldt", "Lower bound")
        self.assertEqual(rm_sphericity.choices_for({}), offered)
        self.assertEqual(rm_sphericity.choices_for({"Sphericity correction": "None"}), offered)
        self.assertEqual(rm_sphericity.choices_for({"Sphericity correction": "Huynh-Feldt"}), offered)
        self.assertEqual(rm_sphericity.choices_for({"Sphericity correction": "Geisser–Greenhouse (one-way)"}),
                         (*offered, "Geisser–Greenhouse (one-way)"))
        self.assertEqual(METHODS[METHOD]["Sphericity correction"], offered)

    def test_an_unknown_choice_is_a_field_error(self):
        for unknown in ("Mauchly", "Huynh–Feldt"):
            with self.subTest(unknown=unknown), self.assertRaises(FieldError) as error:
                tables(long(), correction=unknown)
            self.assertEqual(error.exception.field, "Sphericity correction")
            self.assertEqual(str(error.exception), "Choose None, Geisser–Greenhouse, Huynh-Feldt or Lower bound.")

    def test_three_factors_are_outside_the_new_choice(self):
        with self.assertRaises(FieldError) as error:
            tables(long().assign(Dose=1), factors=(VISIT, CONDITION, "Dose"))
        self.assertEqual(error.exception.field, "Factors")


class DesignErrors(unittest.TestCase):
    def field(self, frame, **kwargs):
        with self.assertRaises(FieldError) as error:
            tables(frame, **kwargs)
        return error.exception

    def test_a_missing_measurement_names_subject_and_cell(self):
        error = self.field(long().drop(index=1))
        self.assertEqual(error.field, "Subject")
        self.assertIn("S1", str(error))
        self.assertIn("Condition 2", str(error))
        self.assertIn("9 combinations", str(error))

    def test_a_duplicate_row_names_the_subject_field(self):
        frame = long()
        error = self.field(pd.concat([frame, frame.iloc[:1]]))
        self.assertEqual(error.field, "Subject")
        self.assertIn("2 measurements", str(error))

    def test_a_blank_or_non_numeric_response_names_the_response_field(self):
        frame = long()
        blank = self.field(frame.assign(Response=frame["Response"].where(frame.index != 5)))
        self.assertEqual(blank.field, "Response")
        self.assertIn("nothing is imputed", str(blank))
        for bad in ("n/a", np.inf):
            text = self.field(frame.assign(Response=frame["Response"].astype(object).where(frame.index != 5, bad)))
            self.assertEqual(text.field, "Response")
            self.assertIn("numeric and finite", str(text))

    def test_a_factor_without_levels_or_with_one_level_names_the_factors_field(self):
        frame = long()
        self.assertEqual(self.field(frame.assign(**{VISIT: np.nan})).field, "Factors")
        self.assertEqual(self.field(frame.assign(**{VISIT: "same"})).field, "Factors")
        self.assertEqual(self.field(frame.assign(**{VISIT: frame[VISIT].where(frame.index != 2)})).field, "Factors")

    def test_a_level_that_only_some_subjects_have_is_a_design_error_on_factors(self):
        extra = pd.DataFrame([{"Subject": "S1", VISIT: "Visit 4", CONDITION: "Condition 1", "Response": 3.0}])
        error = self.field(pd.concat([long(), extra]))
        self.assertEqual(error.field, "Factors")
        self.assertIn("Between-subject and mixed designs", str(error))

    def test_a_spurious_subject_is_a_subject_error(self):
        extra = pd.DataFrame([{"Subject": "S99", VISIT: "Visit 1", CONDITION: "Condition 1", "Response": 3.0}])
        error = self.field(pd.concat([long(), extra]))
        self.assertEqual(error.field, "Subject")
        self.assertIn("S99", str(error))

    def test_roles_subjects_and_blank_subjects(self):
        self.assertEqual(self.field(long(), factors=(VISIT, "Subject")).field, "Factors")
        self.assertEqual(self.field(long().iloc[:9]).field, "Subject")
        frame = long()
        self.assertEqual(self.field(frame.assign(Subject=frame["Subject"].where(frame.index != 4))).field, "Subject")

    def test_a_stratum_without_residual_variance_is_a_response_error(self):
        frame = long()
        shifts = {"Visit 1": 0, "Visit 2": 1, "Visit 3": 2}
        additive = frame.assign(Response=frame["Subject"].str[1:].astype(float) + frame[VISIT].map(shifts)
                                + frame[CONDITION].map({"Condition 1": 0, "Condition 2": 3, "Condition 3": 1}))
        error = self.field(additive)
        self.assertEqual(error.field, "Response")
        self.assertIn("No measurable subject-by-effect residual variance", str(error))
        with self.assertRaises(ValueError) as legacy:
            tables(additive, correction="None")
        self.assertNotIsInstance(legacy.exception, FieldError)

    def test_extreme_scale_is_a_clear_error_and_never_inf_or_nan(self):
        frame = long()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for factor, word in ((1e300, "too large"), (1e-300, "too small")):
                error = self.field(frame.assign(Response=frame["Response"] * factor))
                self.assertEqual(error.field, "Response")
                self.assertIn(word, str(error))

    def test_the_legacy_none_path_keeps_its_plain_value_errors(self):
        with self.assertRaisesRegex(ValueError, "complete"):
            tables(long().drop(index=1), correction="None")


if __name__ == "__main__":
    unittest.main()
