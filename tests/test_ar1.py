"""AR(1) marginal covariance for one within-subject factor, with visits missing.

The numeric oracle is the dense GLS/REML profile used by the packaged reference
(``riferimento.py``): independent subjects, correlation rho**|i-j| on the
confirmed visit indices, and residual degrees of freedom N - rank(X). It does
not call the Trama fitter.
"""
import json
import threading
import tracemalloc
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.linalg import cholesky, solve_triangular
from scipy.optimize import minimize_scalar

from analisi.ar1 import (
    AR1,
    COVARIANCE,
    NO_CORRELATION,
    ORDER_MISMATCH,
    ORDER_REPEATED,
    REASON_DF,
    REASON_EVEN_LAGS,
    REASON_LIMIT,
    REASON_NUMERIC_RANGE,
    REASON_VARIANCE,
    SUBJECT_EFFECTS,
    VISIT_ORDER,
    WALD_DF,
    MixedModelCancelled,
    fit_ar1,
    within_subject_correlation,
)
from analisi.field_error import FieldError
from analisi.mixed import mixed_effects_anova
from analisi.workbench import analyse

HERE = Path(__file__).resolve().parent / "data" / "reml-ar1"
ORDER = ["V1", "V2", "V3", "V4"]


def package_frame():
    frame = pd.read_csv(HERE / "visite.csv")
    frame["Response"] = pd.to_numeric(frame["Response"], errors="coerce")
    return frame


def expected():
    return json.loads((HERE / "atteso.json").read_text(encoding="utf-8"))


def dense_reml(frame, response, visit, group, subject, visits, groups, brackets=((-0.999, 0.999),)):
    """Independent dense REML for a saturated group-by-visit mean and AR(1)."""
    rows = frame.loc[frame[response].notna(), [response, visit, group, subject]]
    visit_index = {name: index for index, name in enumerate(visits)}
    group_index = {name: index for index, name in enumerate(groups)}
    observed_visit = np.array([visit_index[value] for value in rows[visit]])
    observed_group = np.array([group_index[value] for value in rows[group]])
    subjects = rows[subject].to_numpy()
    y = rows[response].to_numpy(dtype=float)
    design = np.eye(len(groups) * len(visits))[observed_group * len(visits) + observed_visit]
    same = subjects[:, None] == subjects[None, :]
    lags = np.abs(observed_visit[:, None] - observed_visit[None, :])
    df = len(y) - design.shape[1]
    if df < 1:
        raise AssertionError("The oracle needs residual degrees of freedom.")

    def fit(rho):
        correlation = np.where(same, np.power(abs(rho), lags) * np.where(lags % 2, np.sign(rho), 1.0), 0.0)
        np.fill_diagonal(correlation, 1.0)
        lower = cholesky(correlation, lower=True)
        transformed_y = solve_triangular(lower, y, lower=True)
        transformed_x = solve_triangular(lower, design, lower=True)
        q, r = np.linalg.qr(transformed_x, mode="reduced")
        coefficients = solve_triangular(r, q.T @ transformed_y)
        residual = transformed_y - transformed_x @ coefficients
        variance = float(residual @ residual / df)
        objective = (
            df * np.log(variance) + 2 * np.log(np.diag(lower)).sum()
            + 2 * np.log(np.abs(np.diag(r))).sum()
        )
        inverse = solve_triangular(r, np.eye(r.shape[0]))
        return objective, variance, coefficients, variance * inverse @ inverse.T

    fits = [minimize_scalar(lambda rho: fit(rho)[0], bounds=bounds,
                            method="bounded", options={"xatol": 1e-12}) for bounds in brackets]
    optimum = min(fits, key=lambda solution: solution.fun)
    _, variance, estimates, covariance = fit(float(optimum.x))
    return {"rho": float(optimum.x), "sigma2": variance, "beta": estimates, "covariance": covariance,
            "df": df}


def ar1(frame, visits=ORDER, **options):
    return mixed_effects_anova(
        frame, "Response", ["Visit", "Group"], "Subject", within=["Visit"],
        covariance=AR1, visit_order=list(visits), **options)


def cell_table(result):
    table = result["Fixed estimates"]
    return {(row["Group"], row["Visit"]): row for _, row in table.iterrows()}


class CorrelationLagTests(unittest.TestCase):
    def test_a_missing_middle_visit_keeps_the_confirmed_distance(self):
        skipped = within_subject_correlation(np.array([0, 2]), -0.5)
        adjacent = within_subject_correlation(np.array([0, 1]), -0.5)
        np.testing.assert_allclose(skipped, [[1.0, 0.25], [0.25, 1.0]])
        np.testing.assert_allclose(adjacent, [[1.0, -0.5], [-0.5, 1.0]])


class PackageContractTests(unittest.TestCase):
    def fit(self, frame=None, visits=ORDER, **options):
        return ar1(package_frame() if frame is None else frame, visits, **options)

    def test_shuffled_rows_match_the_packaged_gls_reference(self):
        reference = expected()
        result = self.fit(posthoc="unadjusted", compare="Group", condition=("Visit",))
        model = result["Model"].iloc[0]
        self.assertEqual(model["Covariance"], AR1)
        self.assertEqual(model["Visit order"], "V1, V2, V3, V4")
        self.assertEqual(model["Denominator df"], WALD_DF)
        self.assertEqual(model["Inference"], "Wald")
        self.assertAlmostEqual(model["Correlation (rho)"], reference["rho"], delta=2e-5)
        self.assertEqual(int(model["Residual df"]), reference["residual_df"])
        self.assertEqual(int(model["Observations used"]), reference["observations"])
        self.assertEqual(int(model["Subjects used"]), reference["subjects"])
        self.assertEqual(int(model["Subjects partial"]), reference["partial_subjects"])
        variance = result["Variance components"].loc["Residual", "Variance"]
        self.assertAlmostEqual(variance / reference["sigma2"], 1, delta=2e-5)
        cells = cell_table(result)
        for cell in reference["cells"]:
            row = cells[(cell["Group"], cell["Visit"])]
            np.testing.assert_allclose(row["Estimate"], cell["Estimate"], rtol=2e-5, atol=2e-5)
            np.testing.assert_allclose(row["SE"], cell["SE"], rtol=2e-5, atol=2e-8)
            self.assertEqual(row["df"], reference["residual_df"])
        comparisons = result["Multiple comparisons"]
        for contrast in reference["contrasts_B_minus_A"]:
            matched = comparisons[comparisons["Condition"] == f"Visit={contrast['Visit']}"]
            self.assertEqual(len(matched), 1)
            row = matched.iloc[0]
            sign = 1.0 if (row["First"], row["Second"]) == ("B", "A") else -1.0
            np.testing.assert_allclose(sign * row["Difference"], contrast["Estimate"], rtol=2e-5, atol=2e-5)
            np.testing.assert_allclose(row["SE"], contrast["SE"], rtol=2e-5, atol=2e-8)
        effects = result["Fixed effects"]
        self.assertTrue((effects["F df2"] == reference["residual_df"]).all())
        self.assertTrue(np.isfinite(effects["F"]).all())

    def test_reversing_rows_or_dropping_one_visit_still_matches_the_dense_oracle(self):
        original = package_frame()
        reversed_rows = original.iloc[::-1].reset_index(drop=True)
        same = self.fit(reversed_rows)
        self.assertAlmostEqual(same["Model"].iloc[0]["Correlation (rho)"], expected()["rho"], delta=2e-5)
        shorter = original.drop(index=original.index[(original["Subject"] == "S01") & (original["Visit"] == "V4")][:1])
        result = self.fit(shorter)
        oracle = dense_reml(shorter, "Response", "Visit", "Group", "Subject", ORDER, ["A", "B"])
        # Group appearance in this file is B then A; the oracle above uses A then B.
        # Compare the correlation and the marginal variance, which do not depend on that coding.
        self.assertAlmostEqual(result["Model"].iloc[0]["Correlation (rho)"], oracle["rho"], delta=2e-5)
        sigma = result["Variance components"].loc["Residual", "Variance"]
        self.assertAlmostEqual(sigma / oracle["sigma2"], 1, delta=2e-5)

    def test_a_different_confirmed_order_changes_the_correlation(self):
        correct = self.fit()["Model"].iloc[0]["Correlation (rho)"]
        swapped = self.fit(visits=["V1", "V3", "V2", "V4"])["Model"].iloc[0]["Correlation (rho)"]
        self.assertGreater(abs(swapped - correct), 1e-3)
        self.assertEqual(self.fit(visits=["V1", "V3", "V2", "V4"])["Model"].iloc[0]["Visit order"],
                         "V1, V3, V2, V4")

    def test_one_subject_missing_v2_matches_an_oracle_that_keeps_lag_two(self):
        frame = package_frame()
        drop = frame.index[(frame["Subject"] == "S02") & (frame["Visit"] == "V2")]
        frame = frame.drop(index=drop)
        result = self.fit(frame)
        present = frame["Response"].notna()
        oracle = dense_reml(frame.loc[present], "Response", "Visit", "Group", "Subject", ORDER,
                            list(dict.fromkeys(frame.loc[present, "Group"])))
        self.assertAlmostEqual(result["Model"].iloc[0]["Correlation (rho)"], oracle["rho"], delta=2e-5)


class SyntheticContractTests(unittest.TestCase):
    def series(self, rho, visits=("V1", "V2", "V3", "V4"), subjects=12, missing=(), seed=7):
        rng = np.random.default_rng(seed)
        rows = []
        scale = np.sqrt(max(1 - rho * rho, 0))
        for subject in range(subjects):
            group = "A" if subject < subjects / 2 else "B"
            shock = rng.normal(size=len(visits))
            latent = np.empty(len(visits))
            latent[0] = shock[0]
            for time in range(1, len(visits)):
                latent[time] = rho * latent[time - 1] + scale * shock[time]
            for time, visit in enumerate(visits):
                if (subject, visit) in missing:
                    response = np.nan
                else:
                    response = (8 if group == "A" else 11) + time + latent[time]
                rows.append((f"S{subject:02d}", group, visit, response))
        return pd.DataFrame(rows, columns=["Subject", "Group", "Visit", "Response"])

    def test_balanced_and_negative_correlation_match_the_dense_oracle(self):
        for rho in (0.35, -0.45):
            with self.subTest(rho=rho):
                frame = self.series(rho, seed=3 if rho > 0 else 9)
                result = ar1(frame)
                oracle = dense_reml(frame, "Response", "Visit", "Group", "Subject", ORDER, ["A", "B"])
                self.assertAlmostEqual(result["Model"].iloc[0]["Correlation (rho)"], oracle["rho"], delta=2e-5)
                sigma = result["Variance components"].loc["Residual", "Variance"]
                self.assertAlmostEqual(sigma / oracle["sigma2"], 1, delta=2e-5)
                cells = cell_table(result)
                for group_index, group in enumerate(["A", "B"]):
                    for visit_index, visit in enumerate(ORDER):
                        slot = group_index * len(ORDER) + visit_index
                        row = cells[(group, visit)]
                        np.testing.assert_allclose(row["Estimate"], oracle["beta"][slot], rtol=2e-5, atol=2e-5)
                        np.testing.assert_allclose(row["SE"], np.sqrt(oracle["covariance"][slot, slot]),
                                                   rtol=2e-5, atol=2e-8)

    def test_a_subject_with_one_visit_stays_in_the_fixed_effects(self):
        frame = self.series(0.4, subjects=8, missing={(7, "V2"), (7, "V3"), (7, "V4")})
        result = ar1(frame)
        self.assertEqual(result["Subjects"].loc["S07", "Observations used"], 1)
        self.assertGreaterEqual(int(result["Model"].iloc[0]["Subjects partial"]), 1)
        oracle = dense_reml(frame, "Response", "Visit", "Group", "Subject", ORDER, ["A", "B"])
        self.assertAlmostEqual(result["Model"].iloc[0]["Correlation (rho)"], oracle["rho"], delta=2e-5)

    def test_duplicate_visit_and_inconsistent_group_are_rejected(self):
        frame = self.series(0.2, subjects=6)
        duplicate = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            ar1(duplicate)
        inconsistent = frame.copy()
        inconsistent.loc[0, "Group"] = "B"
        with self.assertRaisesRegex(ValueError, "between-subject"):
            ar1(inconsistent)

    def test_no_repeated_visit_has_nothing_from_which_to_estimate_correlation(self):
        rows = [("S0", "A", "V1", 1.0), ("S1", "A", "V2", 2.0),
                ("S2", "B", "V1", 3.0), ("S3", "B", "V2", 4.0)]
        frame = pd.DataFrame(rows, columns=["Subject", "Group", "Visit", "Response"])
        with self.assertRaises(FieldError) as caught:
            ar1(frame, visits=["V1", "V2"])
        self.assertEqual(str(caught.exception), NO_CORRELATION)

    def test_only_even_visit_distances_leave_the_sign_unidentified(self):
        frame = self.series(.7, visits=("V1", "V2", "V3"), subjects=24)
        middle = frame["Visit"] == "V2"
        singleton = frame["Subject"].isin(["S00", "S12"])
        observed = (singleton & middle) | (~singleton & ~middle)
        frame.loc[~observed, "Response"] = np.nan
        result = ar1(frame, visits=["V1", "V2", "V3"])
        model = result["Model"].iloc[0]
        self.assertEqual(model["Status"], REASON_EVEN_LAGS)
        self.assertTrue(np.isnan(model["Correlation (rho)"]))
        self.assertTrue(result["Fixed estimates"]["SE"].isna().all())

    def test_multiple_profile_minima_are_refined_before_selecting_the_fit(self):
        rng = np.random.default_rng(7)
        even_visits = [(0, 2)] * 13 + [(2, 4)] * 5 + [(0, 4)] * 3 + [(1, 3)] * 4
        observed = even_visits + [(0, 1), (3, 4), (1, 3, 4), (0, 2, 3), (3,)]
        rows = []
        for subject, visits in enumerate(observed):
            correlation = .72 if subject < len(even_visits) else rng.uniform(-.9, .9)
            distance = np.abs(np.subtract.outer(visits, visits))
            samples = rng.multivariate_normal(np.zeros(len(visits)), correlation ** distance)
            rows.extend((subject, "A", visit, value) for visit, value in zip(visits, samples, strict=True))
        frame = pd.DataFrame(rows, columns=["Subject", "Group", "Visit", "Response"])
        oracle = dense_reml(frame, "Response", "Visit", "Group", "Subject", range(5), ["A"],
                            brackets=((-0.999, 0.), (0., 0.999)))
        fitted = fit_ar1(frame["Response"], frame["Visit"], frame["Subject"], frame["Visit"], 5)
        self.assertIsNone(fitted.reason)
        self.assertAlmostEqual(fitted.rho, oracle["rho"], delta=2e-6)
        self.assertAlmostEqual(fitted.rho, -0.66179365, delta=2e-6)
        np.testing.assert_allclose(fitted.covariance, oracle["covariance"], rtol=2e-6, atol=1e-8)

    def test_estimable_variance_and_wald_tests_survive_large_response_units(self):
        normal = package_frame()
        reference = ar1(normal, posthoc="holm")
        for factor in (5e153, 1e-150):
            with self.subTest(factor=factor):
                result = ar1(normal.assign(Response=normal["Response"] * factor), posthoc="holm")
                self.assertEqual(result["Model"].iloc[0]["Status"], "Converged")
                residual = result["Variance components"].iloc[0]["Variance"] / factor / factor
                self.assertAlmostEqual(residual, reference["Variance components"].iloc[0]["Variance"], places=6)
                np.testing.assert_allclose(result["Fixed effects"]["F"], reference["Fixed effects"]["F"], rtol=2e-6)
                np.testing.assert_allclose(result["Multiple comparisons"]["p"],
                                           reference["Multiple comparisons"]["p"], rtol=2e-6)
                np.testing.assert_allclose(result["Fixed estimates"]["SE"] / factor,
                                           reference["Fixed estimates"]["SE"], rtol=2e-6)

    def test_unrepresentable_response_variance_leaves_inference_empty(self):
        normal = package_frame()
        for factor in (1e155, 1e-166):
            with self.subTest(factor=factor):
                result = ar1(normal.assign(Response=normal["Response"] * factor))
                self.assertEqual(result["Model"].iloc[0]["Status"], REASON_NUMERIC_RANGE)
                self.assertTrue(result["Fixed estimates"]["SE"].isna().all())

    def test_repeated_or_incomplete_order_is_rejected(self):
        frame = self.series(0.2, subjects=6)
        with self.assertRaises(FieldError) as repeated:
            ar1(frame, visits=["V1", "V2", "V2", "V3"])
        self.assertEqual(str(repeated.exception), ORDER_REPEATED)
        with self.assertRaises(FieldError) as incomplete:
            ar1(frame, visits=["V1", "V2", "V3"])
        self.assertEqual(str(incomplete.exception), ORDER_MISMATCH)
        self.assertEqual(incomplete.exception.field, VISIT_ORDER)

    def test_two_within_subject_factors_stay_on_the_random_effects_model(self):
        frame = self.series(0.2, subjects=8)
        frame["Dose"] = np.where(frame["Visit"].isin(["V1", "V2"]), "Low", "High")
        with self.assertRaises(FieldError) as caught:
            mixed_effects_anova(frame, "Response", ["Visit", "Dose"], "Subject",
                                within=["Visit", "Dose"], covariance=AR1, visit_order=ORDER)
        self.assertIn("one within-subject factor", str(caught.exception))

    def test_zero_residual_degrees_of_freedom_leave_the_inference_empty(self):
        rows = [("S0", "A", "V1", 1.0), ("S0", "A", "V2", 2.0),
                ("S1", "B", "V1", 3.0), ("S1", "B", "V2", 4.0)]
        frame = pd.DataFrame(rows, columns=["Subject", "Group", "Visit", "Response"])
        result = ar1(frame, visits=["V1", "V2"])
        self.assertIn("degrees of freedom", result["Model"].iloc[0]["Status"])
        self.assertEqual(result["Model"].iloc[0]["Status"], REASON_DF)
        self.assertTrue(result["Fixed estimates"]["SE"].isna().all())
        self.assertTrue(result["Fixed effects"]["p"].isna().all())
        self.assertTrue(np.isnan(result["Model"].iloc[0]["Correlation (rho)"]))

    def test_constant_response_reports_that_the_variance_is_not_estimable(self):
        frame = self.series(0.2, subjects=6)
        frame["Response"] = 4.0
        result = ar1(frame)
        self.assertEqual(result["Model"].iloc[0]["Status"], REASON_VARIANCE)
        self.assertTrue(result["Fixed estimates"]["SE"].isna().all())
        self.assertTrue(result["Variance components"]["Variance"].isna().all())

    def test_correlation_at_the_boundary_leaves_the_standard_errors_empty(self):
        frame = self.series(0.2, subjects=10, seed=4)
        subject = frame["Subject"].str.extract(r"(\d+)").astype(int)[0]
        frame["Response"] = frame["Group"].map({"A": 0.0, "B": 5.0}) + subject * 3
        result = ar1(frame)
        self.assertEqual(result["Model"].iloc[0]["Status"], REASON_LIMIT)
        self.assertTrue(result["Fixed estimates"]["SE"].isna().all())
        self.assertEqual(result["Model"].iloc[0]["Denominator df"], "Unavailable")


class CurrentRecipeTests(unittest.TestCase):
    def test_a_recipe_without_the_new_option_keeps_the_random_intercept_fit(self):
        values = [(1, 4, 6), (5, 6, 8), (8, 9, None), (11, None, 17),
                  (2, 2, 7), (7, 7, 13), (10, None, 15), (13, 17, 17)]
        data = pd.DataFrame([(subject, level, response) for subject, row in enumerate(values)
                             for level, response in enumerate(row)],
                            columns=["Subject", "Time", "Response"])
        data["Group"] = np.where(data["Subject"] < 4, "A", "B")
        data = data.drop(index=8)
        current = mixed_effects_anova(data, "Response", ["Group", "Time"], "Subject",
                                       within=["Time"], posthoc="unadjusted")
        explicit = mixed_effects_anova(data, "Response", ["Group", "Time"], "Subject",
                                        within=["Time"], posthoc="unadjusted",
                                        covariance=SUBJECT_EFFECTS, visit_order=["ignored", "order"])
        self.assertAlmostEqual(current["Variance components"].loc["Subject random intercept", "Variance"],
                               22.105411, places=5)
        np.testing.assert_allclose(explicit["Fixed effects"][["F", "p"]],
                                   current["Fixed effects"][["F", "p"]], rtol=0, atol=0)
        analysed = analyse("Mixed-effects model (REML)", data, {
            "Input format": "Long table", "Y": "Response", "Subject": "Subject",
            "Within factors": ["Time"], "Between factors": ["Group"], "Post-hoc": "Unadjusted",
        })
        self.assertNotIn(COVARIANCE, {"Input format"})
        self.assertIn("Compound symmetry", analysed.tables["Model"].iloc[0]["Covariance"])
        # The workbench lists within-subject factors before between-subject factors.
        workbench_order = mixed_effects_anova(data, "Response", ["Time", "Group"], "Subject",
                                               within=["Time"], posthoc="unadjusted")
        np.testing.assert_allclose(analysed.tables["Fixed effects"]["F"],
                                   workbench_order["Fixed effects"]["F"])

    def test_cancellation_uses_the_worker_flag(self):
        frame = package_frame()
        with self.assertRaises(MixedModelCancelled):
            ar1(frame, cancel=lambda: True)
        flag = threading.Event()
        flag.set()
        with self.assertRaises(MixedModelCancelled):
            analyse("Mixed-effects model (REML)", frame, {
                "Input format": "Long table", "Y": "Response", "Subject": "Subject",
                "Within factors": ["Visit"], "Between factors": ["Group"],
                COVARIANCE: AR1, VISIT_ORDER: ORDER,
            }, cancel=flag)


class ProjectTests(unittest.TestCase):
    def test_the_example_project_reopens_and_an_edited_response_changes_rho(self):
        from analisi.data import load_project

        loaded = load_project(Path(__file__).resolve().parents[1] / "docs" / "examples" / "reml-ar1-visite.alab")
        sheet = loaded["Visite"]
        method, options = sheet.analyses[0]
        self.assertEqual(method, "Mixed-effects model (REML)")
        self.assertEqual(options[COVARIANCE], AR1)
        self.assertEqual(options[VISIT_ORDER], ORDER)
        self.assertNotIn("Denominator method", options)
        opened = analyse(method, sheet.frame(), options)
        rho = opened.tables["Model"].iloc[0]["Correlation (rho)"]
        self.assertAlmostEqual(rho, expected()["rho"], delta=2e-5)
        self.assertEqual(opened.tables["Model"].iloc[0]["Visit order"], "V1, V2, V3, V4")
        frame = sheet.frame()
        row = frame.index[frame["Response"].notna()][0]
        frame.loc[row, "Response"] = float(frame.loc[row, "Response"]) + 1
        edited = analyse(method, frame, options).tables["Model"].iloc[0]["Correlation (rho)"]
        self.assertTrue(np.isfinite(edited))
        self.assertGreater(abs(edited - rho), 1e-4)


class PerformanceTests(unittest.TestCase):
    def test_one_thousand_subjects_stay_within_a_modest_block_budget(self):
        rng = np.random.default_rng(11)
        visits = [f"V{index}" for index in range(1, 7)]
        rows = []
        for subject in range(1000):
            group = "A" if subject < 500 else "B"
            shock = rng.normal(size=6)
            latent = np.empty(6)
            latent[0] = shock[0]
            for time in range(1, 6):
                latent[time] = 0.55 * latent[time - 1] + np.sqrt(1 - 0.55**2) * shock[time]
            for time, visit in enumerate(visits):
                if subject % 17 == 0 and visit == "V3":
                    continue
                rows.append((f"S{subject:04d}", group, visit, 10 + time + (2 if group == "B" else 0) + latent[time]))
        frame = pd.DataFrame(rows, columns=["Subject", "Group", "Visit", "Response"])
        tracemalloc.start()
        started = tracemalloc.get_traced_memory()[1]
        import time
        clock = time.perf_counter()
        result = ar1(frame, visits=visits)
        elapsed = time.perf_counter() - clock
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertTrue(np.isfinite(result["Model"].iloc[0]["Correlation (rho)"]))
        self.assertLess(elapsed, 15, f"AR(1) on 1000 subjects took {elapsed:.2f}s")
        self.assertLess(peak - started, 64 * 1024 * 1024, f"peak extra memory {peak - started} bytes")
        print(f"AR1 1000x6: {elapsed:.3f}s, traced peak {peak / 1e6:.1f} MB")


if __name__ == "__main__":
    unittest.main()
