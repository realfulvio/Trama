"""Huynh–Feldt and Lower bound corrections of Repeated measures ANOVA (0.97).

The values are checked against three independent sources: the closed formulas written out here from Helmert bases
and the covariance of the contrast scores (``tests.test_rm_sphericity.reference``), the frozen output of
``stats::anova.mlm(test = "Spherical")`` in R on a second synthetic dataset (``tests/data/rm_sphericity``), and
degenerate designs built by hand.
"""
import json
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.linalg import helmert

from analisi import i18n, inference, rm_sphericity
from analisi.field_error import FieldError
from analisi.interface_catalog import CAPTIONS
from analisi.workbench import analyse
from tests.test_rm_sphericity import CONDITION, MATRIX, METHOD, VISIT, long, reference

HF, LB, GG, NONE = "Huynh-Feldt", "Lower bound", "Geisser–Greenhouse", "None"
DATA = Path(__file__).resolve().parent / "data" / "rm_sphericity"
CORRECTED = (HF, LB)


def run(frame, correction, factors=(VISIT, CONDITION), response="Response"):
    recipe = {"Response": response, "Factors": list(factors), "Subject": "Subject",
              "Sphericity correction": correction}
    return analyse(METHOD, frame, recipe).tables


def hf_epsilon(gg, dimension, subjects):
    """The Huynh–Feldt epsilon of the literature, before any limit, from the Greenhouse–Geisser one."""
    return (subjects * dimension * gg - 2) / (dimension * (subjects - 1 - dimension * gg))


def one_way(matrix):
    """Long table of one within-subject factor from a subjects × levels matrix."""
    return long(np.asarray(matrix, dtype=float), levels=1).drop(columns=CONDITION)


def independent(wide):
    """Dimension, Greenhouse–Geisser epsilon and subjects of a subjects × levels matrix, from its Helmert scores."""
    scores = np.asarray(wide, dtype=float) @ helmert(wide.shape[1]).T
    eigenvalues = np.linalg.eigvalsh(np.atleast_2d(np.cov(scores, rowvar=False, ddof=1)))
    dimension = scores.shape[1]
    return dimension, eigenvalues.sum() ** 2 / (dimension * np.square(eigenvalues).sum()), scores.shape[0]


class ClosedFormulas(unittest.TestCase):
    def test_every_effect_of_a_two_factor_design_follows_the_formulas(self):
        frame, subjects = long(), 5
        for correction in CORRECTED:
            sheet = run(frame, correction)["Sphericity"]
            self.assertEqual(list(sheet), rm_sphericity.ESTIMATED_COLUMNS)
            self.assertEqual(sheet["Correction"].unique().tolist(), [correction])
            for term, (dimension, gg, statistic, _, plain) in reference(frame).items():
                with self.subTest(correction=correction, term=term):
                    row = sheet.set_index("Term").loc[term]
                    epsilon = min(1.0, hf_epsilon(gg, dimension, subjects)) if correction == HF else 1 / dimension
                    self.assertEqual(row["Contrast dimension"], dimension)
                    np.testing.assert_allclose(
                        [row["GG ε"], row["Applied epsilon"], row["F"], row["F df1"], row["F df2"], row["p"],
                         row["Uncorrected p"]],
                        [gg, epsilon, statistic, dimension * epsilon, (subjects - 1) * dimension * epsilon,
                         stats.f.sf(statistic, dimension * epsilon, (subjects - 1) * dimension * epsilon), plain],
                        rtol=1e-10)

    def test_one_factor_follows_the_formulas_and_keeps_the_greenhouse_geisser_table(self):
        frame = long().query(f"{CONDITION} == 'Condition 1'")
        wide = frame.pivot(index="Subject", columns=VISIT, values="Response")
        dimension, gg, subjects = independent(wide)
        scores = wide.to_numpy() @ helmert(3).T
        statistic = subjects * np.square(scores.mean(axis=0)).sum() / np.trace(np.cov(scores.T))
        for correction in CORRECTED:
            with self.subTest(correction=correction):
                result = run(frame, correction, (VISIT,))
                self.assertEqual(list(result), ["ANOVA", "Sphericity"])
                self.assertEqual(result["Sphericity"]["Term"].tolist(), [VISIT])
                epsilon = min(1.0, hf_epsilon(gg, dimension, subjects)) if correction == HF else 1 / dimension
                row = result["Sphericity"].iloc[0]
                np.testing.assert_allclose(
                    [row["GG ε"], row["Applied epsilon"], row["F"], row["F df1"], row["F df2"], row["p"]],
                    [gg, epsilon, statistic, dimension * epsilon, (subjects - 1) * dimension * epsilon,
                     stats.f.sf(statistic, dimension * epsilon, (subjects - 1) * dimension * epsilon)], rtol=1e-10)
        # The Greenhouse–Geisser choice and None keep their one-factor tables, with no Sphericity sheet.
        self.assertEqual(list(run(frame, GG, (VISIT,))), ["ANOVA"])
        self.assertEqual(list(run(frame, NONE, (VISIT,))), ["ANOVA"])

    def test_huynh_feldt_above_one_is_limited_to_one_and_says_so(self):
        frame, subjects = long(), 5
        sheet = run(frame, HF)["Sphericity"].set_index("Term")
        limited = []
        for term, (dimension, gg, *_) in reference(frame).items():
            raw, row = hf_epsilon(gg, dimension, subjects), sheet.loc[term]
            with self.subTest(term=term, raw=raw):
                if raw > 1:
                    limited.append(term)
                    self.assertEqual(row["Applied epsilon"], 1.0)
                    self.assertEqual(row["F df1"], dimension)
                    self.assertEqual(row["p"], row["Uncorrected p"])
                    self.assertIn("limited to 1", row["Note"])
                    self.assertIn(f"{raw:.6g}", row["Note"])
                else:
                    self.assertAlmostEqual(row["Applied epsilon"], raw, places=12)
                    self.assertEqual(row["Note"], "")
        self.assertEqual(limited, [VISIT, f"{VISIT}:{CONDITION}"])

    def test_the_lower_bound_is_one_over_the_contrast_dimension(self):
        frame = long()
        sheet = run(frame, LB)["Sphericity"].set_index("Term")
        for term, (dimension, _, statistic, *_) in reference(frame).items():
            with self.subTest(term=term):
                row = sheet.loc[term]
                self.assertAlmostEqual(row["Applied epsilon"], 1 / dimension, places=15)
                self.assertAlmostEqual(row["F df1"], 1.0, places=12)
                self.assertAlmostEqual(row["F df2"], 4.0, places=12)
                self.assertAlmostEqual(row["p"], stats.f.sf(statistic, 1, 4), places=14)

    def test_epsilons_are_ordered_from_the_lower_bound_to_one(self):
        frame = long()
        epsilon = {name: run(frame, name)["Sphericity"]["Applied epsilon"] for name in (LB, HF)}
        gg = run(frame, GG)["Sphericity"]["GG ε"]
        for term in range(3):
            self.assertLessEqual(epsilon[LB][term], gg[term] + 1e-15)
            self.assertLessEqual(gg[term], epsilon[HF][term] + 1e-15)
            self.assertLessEqual(epsilon[HF][term], 1.0)

    def test_the_anova_sheet_keeps_ss_ms_and_f_and_reports_both_epsilons(self):
        frame = long()
        plain, gg = run(frame, NONE)["ANOVA"], run(frame, GG)["ANOVA"]
        for correction in CORRECTED:
            with self.subTest(correction=correction):
                result = run(frame, correction)
                anova, sphericity = result["ANOVA"], result["Sphericity"].set_index("Term")
                self.assertEqual(list(anova), ["SS", "df", "MS", "F", "F df1", "F df2", "GG ε", "Applied epsilon", "p"])
                self.assertEqual(list(anova.index), list(plain.index))
                for column in ("SS", "df", "MS", "F"):
                    pd.testing.assert_series_equal(anova[column], plain[column], check_exact=True)
                pd.testing.assert_series_equal(anova["GG ε"], gg["GG ε"], check_exact=True)
                for term in sphericity.index:
                    for column in ("F df1", "F df2", "p", "Applied epsilon", "GG ε"):
                        self.assertEqual(anova.loc[term, column], sphericity.loc[term, column], (term, column))
                errors = [name for name in anova.index if name.startswith("Subject")]
                self.assertTrue(anova.loc[errors, ["F df1", "F df2", "GG ε", "Applied epsilon", "p"]].isna().all().all())

    def test_the_previous_choices_keep_their_sheets(self):
        frame = long()
        none, gg = run(frame, NONE), run(frame, GG)
        self.assertEqual(list(none), ["ANOVA"])
        self.assertEqual(list(none["ANOVA"]), ["SS", "df", "MS", "F", "F df1", "F df2", "p"])
        self.assertEqual(list(gg), ["ANOVA", "Sphericity"])
        self.assertEqual(list(gg["ANOVA"]), ["SS", "df", "MS", "F", "F df1", "F df2", "GG ε", "p"])
        self.assertEqual(list(gg["Sphericity"]), rm_sphericity.COLUMNS)


class AgainstR(unittest.TestCase):
    """A second dataset (8 subjects, 4 × 3) against R's stats::anova.mlm, frozen in reference-r.json."""

    @classmethod
    def setUpClass(cls):
        cls.frame = pd.read_csv(DATA / "second-dataset.csv")
        cls.reference = json.loads((DATA / "reference-r.json").read_text(encoding="utf-8"))

    def cases(self):
        yield "Time", self.frame, ("Time", "Dose"), "Time"
        yield "Dose", self.frame, ("Time", "Dose"), "Dose"
        yield "Time:Dose", self.frame, ("Time", "Dose"), "Time:Dose"
        yield "One-way Time", self.frame.query("Dose == 'D1'"), ("Time",), "Time"
        yield "One-way Dose", self.frame.query("Time == 'T1'"), ("Dose",), "Dose"

    def test_the_reference_file_documents_its_source(self):
        info = self.reference["reference"]
        self.assertEqual(info["program"], "R")
        self.assertRegex(info["version"], r"^\d+\.\d+\.\d+ \(\d{4}-\d{2}-\d{2}\)$")
        self.assertTrue((DATA / info["script"]).is_file())
        self.assertEqual(self.reference["subjects"], self.frame["Subject"].nunique())

    def test_epsilons_degrees_of_freedom_and_p_values_match_r(self):
        for key, frame, factors, term in self.cases():
            ref = self.reference["effects"][key]
            n, d = ref["n"], ref["numdf"]
            with self.subTest(case=key):
                gg = run(frame, GG, factors, "Value")["ANOVA"].loc[term]
                np.testing.assert_allclose([gg["GG ε"], gg["F"], gg["p"]], [ref["gg"], ref["F"], ref["gg_p"]], rtol=1e-7)
                hf = run(frame, HF, factors, "Value")["Sphericity"].set_index("Term").loc[term]
                applied = min(1.0, ref["hf"])
                self.assertEqual(hf["Contrast dimension"], d)
                np.testing.assert_allclose(
                    [hf["GG ε"], hf["Applied epsilon"], hf["F"], hf["F df1"], hf["F df2"], hf["p"], hf["Uncorrected p"]],
                    [ref["gg"], applied, ref["F"], d * applied, ref["dendf"] * applied, ref["hf_p"], ref["p"]],
                    rtol=1e-7)
                self.assertEqual("limited to 1" in hf["Note"], ref["hf"] > 1)
                lower = run(frame, LB, factors, "Value")["Sphericity"].set_index("Term").loc[term]
                np.testing.assert_allclose(
                    [lower["Applied epsilon"], lower["F df1"], lower["F df2"], lower["p"]],
                    [1 / d, 1.0, ref["dendf"] / d, ref["lb_p"]], rtol=1e-7)
                self.assertEqual(ref["dendf"], (n - 1) * d)

    def test_the_dataset_exercises_both_sides_of_the_limit(self):
        raw = [ref["hf"] for ref in self.reference["effects"].values()]
        self.assertTrue(any(value > 1 for value in raw))
        self.assertTrue(any(value < 1 for value in raw))


class Degenerate(unittest.TestCase):
    @staticmethod
    def equal_eigenvalue_scores():
        """Three subjects whose scores on a 3-level factor have the identity as covariance, up to a constant."""
        return np.array([[1.0, 0.0], [-0.5, np.sqrt(3) / 2], [-0.5, -np.sqrt(3) / 2]])

    def test_two_levels_give_exactly_one_without_correction_of_the_test(self):
        frame = long(MATRIX[:, [0, 1, 3, 4]], levels=2)
        frame[VISIT] = frame[VISIT].replace({"Visit 3": "Visit 2"})
        for correction in CORRECTED:
            with self.subTest(correction=correction):
                result = run(frame, correction)
                sheet = result["Sphericity"]
                self.assertEqual(sheet["Applied epsilon"].tolist(), [1.0, 1.0, 1.0])
                self.assertEqual(sheet["Contrast dimension"].tolist(), [1, 1, 1])
                np.testing.assert_array_equal(sheet["p"], sheet["Uncorrected p"])
                self.assertTrue(sheet["Note"].str.contains("d = 1").all())
                self.assertTrue(np.isfinite(sheet.select_dtypes("number").to_numpy()).all())
                np.testing.assert_array_equal(result["ANOVA"]["p"].to_numpy(), run(frame, NONE)["ANOVA"]["p"].to_numpy())

    def test_a_singular_covariance_with_residual_variance_is_still_estimable(self):
        # Three subjects and four levels: the 3 × 3 covariance of the scores has rank 2.
        frame = one_way(MATRIX[:3, :4] + np.array([0, 1, 4, 2]))
        wide = frame.pivot(index="Subject", columns=VISIT, values="Response")
        scores = wide.to_numpy() @ helmert(4).T
        self.assertEqual(np.linalg.matrix_rank(np.cov(scores.T)), 2)
        dimension, gg, subjects = independent(wide)
        raw = hf_epsilon(gg, dimension, subjects)
        self.assertGreater(subjects - 1 - dimension * gg, 1e-3)
        row = run(frame, HF, (VISIT,))["Sphericity"].iloc[0]
        self.assertAlmostEqual(row["Applied epsilon"], min(1.0, raw), places=12)
        self.assertTrue(np.isfinite(row[["F df1", "F df2", "p"]].astype(float)).all())
        lower = run(frame, LB, (VISIT,))["Sphericity"].iloc[0]
        self.assertAlmostEqual(lower["Applied epsilon"], 1 / 3, places=15)

    def test_equal_eigenvalues_make_huynh_feldt_undefined_and_nothing_else(self):
        scores = self.equal_eigenvalue_scores()
        matrix = 10 + scores @ helmert(3) + np.array([0.0, 1.0, 3.0]) + np.array([[0.0], [2.0], [5.0]])
        frame = one_way(matrix)
        sheet = run(frame, HF, (VISIT,))
        row = sheet["Sphericity"].iloc[0]
        self.assertTrue(np.isnan(row[["Applied epsilon", "F df1", "F df2", "p"]].astype(float)).all())
        self.assertIn("undefined", row["Note"])
        self.assertIn("n = 3 subjects", row["Note"])
        self.assertAlmostEqual(row["GG ε"], 1.0, places=12)
        self.assertTrue(np.isfinite(row["F"]) and np.isfinite(row["Uncorrected p"]))
        anova = sheet["ANOVA"].loc[VISIT]
        self.assertTrue(np.isnan(anova["p"]) and np.isnan(anova["Applied epsilon"]))
        self.assertEqual(anova["F"], row["F"])
        # The other choices of the same data are not affected.
        self.assertTrue(np.isfinite(run(frame, LB, (VISIT,))["Sphericity"].iloc[0]["p"]))
        self.assertTrue(np.isfinite(run(frame, GG, (VISIT,))["ANOVA"].loc[VISIT, "p"]))

    def test_an_undefined_effect_keeps_the_estimable_effects_of_the_same_design(self):
        rng = np.random.default_rng(97)
        scores, coefficients = self.equal_eigenvalue_scores(), rng.normal(size=(3, 2))
        sign = np.array([1.0, -1.0]) / np.sqrt(2)
        basis = helmert(3)
        cube = (10 + np.array([0.0, 2.0, 5.0])[:, None, None]
                + (scores @ basis)[:, :, None] + np.array([0.0, 1.0, 3.0])[None, :, None]
                + np.array([[2.5], [0.5], [0.0]])[:, None, :] * sign[None, None, :]
                + np.einsum("nk,ki,j->nij", coefficients, basis, sign))
        frame = pd.DataFrame([(f"S{s + 1}", f"A{i + 1}", f"B{j + 1}", cube[s, i, j])
                              for s in range(3) for i in range(3) for j in range(2)],
                             columns=["Subject", "A", "B", "Response"])
        sheet = run(frame, HF, ("A", "B"))["Sphericity"].set_index("Term")
        self.assertTrue(np.isnan(sheet.loc["A", ["Applied epsilon", "F df1", "F df2", "p"]].astype(float)).all())
        self.assertIn("undefined", sheet.loc["A", "Note"])
        self.assertEqual(sheet.loc["B", "Applied epsilon"], 1.0)
        self.assertEqual(sheet.loc["B", "p"], sheet.loc["B", "Uncorrected p"])
        independent_values = reference(frame, ("A", "B"))
        dimension, gg, statistic, _, plain = independent_values["A:B"]
        epsilon = min(1.0, hf_epsilon(gg, dimension, 3))
        np.testing.assert_allclose(
            [sheet.loc["A:B", "Applied epsilon"], sheet.loc["A:B", "F"], sheet.loc["A:B", "F df1"],
             sheet.loc["A:B", "p"]],
            [epsilon, statistic, dimension * epsilon, stats.f.sf(statistic, dimension * epsilon, 2 * dimension * epsilon)],
            rtol=1e-9)

    def test_two_subjects_leave_huynh_feldt_undefined_but_not_the_lower_bound(self):
        frame = one_way(MATRIX[:2, :3])
        row = run(frame, HF, (VISIT,))["Sphericity"].iloc[0]
        self.assertTrue(np.isnan(row[["Applied epsilon", "p"]].astype(float)).all())
        self.assertIn("n = 2 subjects", row["Note"])
        lower = run(frame, LB, (VISIT,))["Sphericity"].iloc[0]
        self.assertAlmostEqual(lower["F df1"], 1.0, places=12)
        self.assertAlmostEqual(lower["F df2"], 1.0, places=12)
        self.assertAlmostEqual(lower["p"], stats.f.sf(lower["F"], 1, 1), places=14)

    def test_the_formula_helpers(self):
        self.assertAlmostEqual(rm_sphericity.huynh_feldt(0.6, 4, 12), (12 * 4 * 0.6 - 2) / (4 * (11 - 4 * 0.6)), places=14)
        self.assertIsNone(rm_sphericity.huynh_feldt(1 / 3, 3, 2))
        self.assertIsNone(rm_sphericity.huynh_feldt(0.5, 4, 3))
        self.assertIsNone(rm_sphericity.huynh_feldt(float("nan"), 4, 9))
        epsilon, note = rm_sphericity.applied_epsilon(rm_sphericity.HUYNH_FELDT, 1 / 3, 3, 10)
        self.assertAlmostEqual(epsilon, 1 / 3, places=14)
        self.assertEqual(note, "")
        epsilon, note = rm_sphericity.applied_epsilon(rm_sphericity.HUYNH_FELDT, 1 / 3 - 1e-6, 3, 10)
        self.assertEqual(epsilon, 1 / 3)
        self.assertIn("below 1/d", note)
        self.assertEqual(rm_sphericity.applied_epsilon(rm_sphericity.LOWER_BOUND, 0.8, 1, 9)[0], 1.0)
        self.assertEqual(rm_sphericity.applied_epsilon(rm_sphericity.HUYNH_FELDT, 0.7, 1, 9)[0], 1.0)


class Invariances(unittest.TestCase):
    def sheet(self, frame, correction, **kwargs):
        return run(frame, correction, **kwargs)["Sphericity"].set_index("Term")

    def test_offsets_scale_row_order_and_factor_order_do_not_change_the_result(self):
        frame = long()
        shifted = frame.assign(Response=8.0 * frame["Response"] + frame["Subject"].map(
            {"S1": 1e6, "S2": -1e6, "S3": 2e6, "S4": -2e6, "S5": 5e5}))
        for correction in CORRECTED:
            plain = self.sheet(frame, correction)
            with self.subTest(correction=correction):
                changed = self.sheet(shifted.sample(frac=1, random_state=3), correction).reindex(plain.index)
                np.testing.assert_allclose(changed["Applied epsilon"], plain["Applied epsilon"], rtol=1e-9)
                np.testing.assert_allclose(changed["F"], plain["F"], rtol=1e-8)
                np.testing.assert_allclose(changed["p"], plain["p"], rtol=1e-7)
                swapped = self.sheet(frame, correction, factors=(CONDITION, VISIT))
                self.assertEqual(list(swapped.index), [CONDITION, VISIT, f"{CONDITION}:{VISIT}"])
                numeric = ["GG ε", "Applied epsilon", "F", "F df1", "F df2", "p", "Uncorrected p"]
                for was, now in ((VISIT, VISIT), (CONDITION, CONDITION), (f"{VISIT}:{CONDITION}", f"{CONDITION}:{VISIT}")):
                    np.testing.assert_allclose(swapped.loc[now, numeric].astype(float), plain.loc[was, numeric].astype(float),
                                               rtol=1e-12)
                    self.assertEqual(swapped.loc[now, "Note"], plain.loc[was, "Note"])
                    self.assertEqual(swapped.loc[now, "Contrast dimension"], plain.loc[was, "Contrast dimension"])

    def test_a_translation_within_each_subject_changes_nothing(self):
        frame = long()
        offsets = {"S1": 123456.5, "S2": -98765.25, "S3": 0.75, "S4": 1e6, "S5": -3e6}
        moved = frame.assign(Response=frame["Response"] + frame["Subject"].map(offsets))
        for correction in CORRECTED:
            with self.subTest(correction=correction):
                a, b = self.sheet(frame, correction), self.sheet(moved, correction)
                np.testing.assert_allclose(b["Applied epsilon"], a["Applied epsilon"], rtol=1e-8)
                np.testing.assert_allclose(b["p"], a["p"], rtol=1e-6)

    def test_small_and_large_numbers_keep_epsilon_and_stay_finite(self):
        base = {correction: self.sheet(long(), correction) for correction in CORRECTED}
        for factor in (1e-100, 1e-3, 1e12, 1e100):
            for correction in CORRECTED:
                with self.subTest(factor=factor, correction=correction), warnings.catch_warnings():
                    warnings.simplefilter("error")
                    scaled = self.sheet(long().assign(Response=long()["Response"] * factor), correction)
                np.testing.assert_allclose(scaled["Applied epsilon"], base[correction]["Applied epsilon"], rtol=1e-9)
                np.testing.assert_allclose(scaled["p"], base[correction]["p"], rtol=1e-7)
                self.assertTrue(np.isfinite(scaled.select_dtypes("number").to_numpy()).all())

    def test_a_large_design_stays_finite_for_both_choices(self):
        rng = np.random.default_rng(97)
        n, a, b = 120, 6, 5
        cube = rng.normal(size=(n, a, b)) + np.arange(a)[None, :, None] * .3 + rng.normal(size=(n, 1, 1)) * 5
        frame = pd.DataFrame([(s, i, j, cube[s, i, j]) for s in range(n) for i in range(a) for j in range(b)],
                             columns=["Subject", VISIT, CONDITION, "Response"])
        for correction in CORRECTED:
            sheet = self.sheet(frame, correction)
            self.assertEqual(sheet["Contrast dimension"].tolist(), [5, 4, 20])
            self.assertTrue(np.isfinite(sheet.select_dtypes("number").to_numpy()).all())
            self.assertTrue(((sheet["Applied epsilon"] >= 1 / sheet["Contrast dimension"])
                             & (sheet["Applied epsilon"] <= 1)).all())


class Validation(unittest.TestCase):
    def message(self, frame, correction, **kwargs):
        with self.assertRaises(FieldError) as error:
            run(frame, correction, **kwargs)
        return error.exception

    def test_design_errors_name_the_same_field_and_sentence_as_greenhouse_geisser(self):
        frame = long()
        cases = {
            "missing cell": (frame.drop(index=1), {}),
            "repeated cell": (pd.concat([frame, frame.iloc[:1]]), {}),
            "blank response": (frame.assign(Response=frame["Response"].where(frame.index != 5)), {}),
            "infinite response": (frame.assign(Response=frame["Response"].astype(object).where(frame.index != 5, np.inf)), {}),
            "one level": (frame.assign(**{VISIT: "same"}), {}),
            "three factors": (frame.assign(Dose=1), {"factors": (VISIT, CONDITION, "Dose")}),
            "factor as subject": (frame, {"factors": (VISIT, "Subject")}),
        }
        for label, (data, kwargs) in cases.items():
            reference_error = self.message(data, GG, **kwargs)
            for correction in CORRECTED:
                with self.subTest(case=label, correction=correction):
                    error = self.message(data, correction, **kwargs)
                    self.assertEqual((error.field, str(error)), (reference_error.field, str(reference_error)))

    def test_a_stratum_without_residual_variance_is_a_response_error_for_both(self):
        frame = long()
        additive = frame.assign(Response=frame["Subject"].str[1:].astype(float)
                                + frame[VISIT].map({"Visit 1": 0, "Visit 2": 1, "Visit 3": 2})
                                + frame[CONDITION].map({"Condition 1": 0, "Condition 2": 3, "Condition 3": 1}))
        for correction in CORRECTED:
            with self.subTest(correction=correction):
                error = self.message(additive, correction)
                self.assertEqual(error.field, "Response")
                self.assertIn("No measurable subject-by-effect residual variance", str(error))

    def test_extreme_scales_are_field_errors_for_both(self):
        frame = long()
        for correction in CORRECTED:
            for factor, word in ((1e300, "too large"), (1e-300, "too small")):
                with self.subTest(correction=correction, factor=factor), warnings.catch_warnings():
                    warnings.simplefilter("error")
                    error = self.message(frame.assign(Response=frame["Response"] * factor), correction)
                self.assertEqual(error.field, "Response")
                self.assertIn(word, str(error))

    def test_the_engine_rejects_unknown_tokens(self):
        with self.assertRaisesRegex(ValueError, "Unknown sphericity correction"):
            inference.repeated_measures_anova(long(), "Response", [VISIT, CONDITION], "Subject", correction="mauchly")

    def test_the_historical_choice_is_still_accepted_and_one_way_only(self):
        frame = long().query(f"{CONDITION} == 'Condition 1'")
        result = run(frame, "Geisser–Greenhouse (one-way)", (VISIT,))
        self.assertEqual(list(result), ["ANOVA"])


class Wording(unittest.TestCase):
    def test_the_captions_and_the_choice_sentence_are_translated(self):
        self.assertEqual(CAPTIONS["Huynh-Feldt"], "Huynh–Feldt")
        self.assertEqual(CAPTIONS["Lower bound"], "Limite inferiore")
        self.assertEqual(i18n.CATALOGS["en"]["rm.sphericity.error.choice"], rm_sphericity.ERRORS["choice"])
        italian = i18n.CATALOGS["it"]["rm.sphericity.error.choice"]
        for caption in ("Nessuno", "Geisser–Greenhouse", "Huynh–Feldt", "Limite inferiore"):
            self.assertIn(caption, italian)
        for key in ("note.hf", "note.lower"):
            for language in ("en", "it"):
                self.assertTrue(i18n.CATALOGS[language]["rm.sphericity." + key], (language, key))
        for language in ("en", "it"):
            self.assertNotIn("no Huynh–Feldt", i18n.CATALOGS[language]["rm.sphericity.note.gg"])
            self.assertNotIn("correzione di Huynh–Feldt", i18n.CATALOGS[language]["rm.sphericity.note.gg"])

    def test_the_notes_of_the_sheet_are_english_sentences_with_the_numbers_they_explain(self):
        sheet = run(long(), HF)["Sphericity"].set_index("Term")
        self.assertRegex(sheet.loc[VISIT, "Note"], r"^Huynh–Feldt estimate [0-9.]+ is above 1 and was limited to 1")
        self.assertEqual(run(long(), LB)["Sphericity"]["Note"].str.startswith("Lower bound 1/d with d = ").all(), True)


if __name__ == "__main__":
    unittest.main()
