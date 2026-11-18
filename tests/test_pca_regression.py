"""Principal component regression: numerics, masks, compatibility and field errors."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from analisi import exploration, pca_graphs, pca_regression, pca_reports, pca_retention
from analisi.field_error import FieldError
from analisi.workbench import METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "pca_regression"
METHOD = "Principal component analysis"
PREDICTORS = ["Conductivity", "Temperature"]
ENABLE, RESPONSE, CONFIDENCE, PLOT = (pca_regression.ENABLE, pca_regression.RESPONSE,
                                     pca_regression.CONFIDENCE, pca_regression.PLOT)
COEF, SCORES_COEF, MODEL, FITTED = (pca_regression.COEFFICIENTS, pca_regression.SCORE_COEFFICIENTS,
                                    pca_regression.MODEL, pca_regression.FITTED)
RESULT = ["Estimate", "SE", "Lower", "Upper", "t", "p"]
ON = {ENABLE: True, RESPONSE: "Response", CONFIDENCE: 90.0, PLOT: "Keep PCA"}
FIXED_ONE = {"Selection": "Fixed number", "Retained components": 1}


def fixture(name):
    return pd.read_csv(DATA / f"pcr-{name}.csv", index_col="Source row")


def options(standardize=True, **extra):
    return {"Variables": PREDICTORS, "Standardize": standardize, "Selection": "All", **extra}


def run(frame, standardize=True, **extra):
    return analyse(METHOD, frame, options(standardize, **extra))


def oracle(frame, standardize, count, level=90.0, response="Response"):
    """Eigendecomposition of the predictor covariance followed by a direct least squares with inv(Z'Z)."""
    x = frame[PREDICTORS].to_numpy(dtype=float)
    complete = np.isfinite(x).all(axis=1)
    x = x[complete]
    center = x.mean(axis=0)
    scale = x.std(axis=0, ddof=1) if standardize else np.ones(len(PREDICTORS))
    transformed = (x - center) / scale
    values, vectors = np.linalg.eigh(np.cov(transformed, rowvar=False, ddof=1))
    values, vectors = values[::-1], vectors[:, ::-1]
    if count is None:
        count = int(np.sum(values > values[0] * 1e-10))
    basis = vectors[:, :count]
    target = frame[response].to_numpy(dtype=float)[complete]
    in_fit = np.isfinite(target)
    z = np.column_stack((np.ones(len(x)), transformed @ basis))
    train, y = z[in_fit], target[in_fit]
    b = np.linalg.lstsq(train, y, rcond=None)[0]
    df = len(train) - count - 1
    predicted = z @ b
    sse = float(np.sum((y - predicted[in_fit]) ** 2))
    mse = sse / df
    covariance = mse * np.linalg.inv(train.T @ train)
    slopes = basis / scale[:, None]
    convert = np.block([[np.ones((1, 1)), (-center @ slopes)[None, :]],
                        [np.zeros((len(scale), 1)), slopes]])
    critical = stats.t.ppf((100 + level) / 200, df)
    mean_var = np.einsum("ij,jk,ik->i", z, covariance, z)
    se = np.sqrt(np.diag(convert @ covariance @ convert.T))
    raw = convert @ b
    t = raw / se
    return {
        "raw": np.column_stack((raw, se, raw - critical * se, raw + critical * se, t,
                                2 * stats.t.sf(np.abs(t), df))),
        "mean": predicted, "in_fit": in_fit, "ids": frame.index[complete].tolist(),
        "mean_half": critical * np.sqrt(mean_var), "prediction_half": critical * np.sqrt(mean_var + mse),
        "sse": sse, "mse": mse, "df": df, "count": count, "basis": basis,
    }


def close(actual, wanted):
    np.testing.assert_allclose(actual, wanted, rtol=2e-9, atol=2e-10, equal_nan=True)


class NumericTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture("main")

    def check(self, frame, standardize, count, **extra):
        want = oracle(frame, standardize, count)
        selection = {"Selection": "All"} if count is None else {**FIXED_ONE, "Retained components": count}
        tables = run(frame, standardize, **ON, **selection, **extra).tables
        self.assertEqual(list(tables[COEF]["Term"]), ["Intercept", *PREDICTORS])
        close(tables[COEF][RESULT], want["raw"])
        fitted = tables[FITTED]
        self.assertEqual(list(fitted["Source row"]), want["ids"])
        self.assertEqual(list(fitted["Used in fit"]), want["in_fit"].tolist())
        close(fitted["Fitted"], want["mean"])
        close(fitted["Mean upper"] - fitted["Fitted"], want["mean_half"])
        close(fitted["Prediction upper"] - fitted["Fitted"], want["prediction_half"])
        close(fitted["Fitted"] - fitted["Mean lower"], want["mean_half"])
        close(fitted["Fitted"] - fitted["Prediction lower"], want["prediction_half"])
        model = tables[MODEL].iloc[0]
        close([model["SSE"], model["MSE"]], [want["sse"], want["mse"]])
        self.assertEqual((model["Residual df"], model["Components"], model["Model df"]),
                         (want["df"], want["count"], want["count"]))
        return tables, want

    def test_centered_and_standardized_one_component_and_all_match_the_oracle(self):
        for standardize, count in ((False, 1), (True, 1), (True, None), (False, None)):
            with self.subTest(standardize=standardize, count=count):
                self.check(self.data, standardize, count)

    def test_frozen_reference_values(self):
        expected = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
        for name, standardize, count, frame in (("centered_one", False, 1, self.data),
                                                ("standardized_one", True, 1, self.data),
                                                ("standardized_all", True, None, self.data),
                                                ("collinear_all", True, None, fixture("rank"))):
            with self.subTest(name):
                selection = {"Selection": "All"} if count is None else FIXED_ONE
                tables = run(frame, standardize, **ON, **selection).tables
                close(tables[COEF]["Estimate"], expected[name]["raw_coefficients"])
                close(tables[FITTED]["Fitted"].iloc[-1], expected[name]["last_fitted"])
                model = tables[MODEL].iloc[0]
                close([model["SSE"], model["MSE"]], expected[name]["sse_mse"])

    def test_row_counts_and_the_prediction_only_row(self):
        tables = run(self.data, True, **ON, **FIXED_ONE).tables
        model = tables[MODEL].iloc[0]
        self.assertEqual((model["PCA rows"], model["Regression rows"], model["Residual df"]), (11, 10, 8))
        fitted = tables[FITTED]
        self.assertEqual(len(fitted), 11)
        self.assertNotIn("missing X", list(fitted["Source row"]))
        last = fitted.iloc[-1]
        self.assertEqual(last["Source row"], "prediction only")
        self.assertFalse(last["Used in fit"])
        self.assertTrue(np.isnan(last["Observed"]) and np.isnan(last["Residual"]))
        self.assertTrue(np.isfinite(last[["Fitted", "Mean lower", "Prediction upper"]].to_numpy(dtype=float)).all())
        self.assertTrue(fitted["Used in fit"].dtype == bool)

    def test_interval_ordering_and_model_sheet_values(self):
        tables = run(self.data, True, **ON, **FIXED_ONE).tables
        fitted = tables[FITTED]
        self.assertTrue(((fitted["Prediction lower"] < fitted["Mean lower"]) & (fitted["Mean lower"] < fitted["Fitted"])
                         & (fitted["Fitted"] < fitted["Mean upper"])
                         & (fitted["Mean upper"] < fitted["Prediction upper"])).all())
        model = tables[MODEL].iloc[0]
        y = self.data["Response"].dropna()
        y = y[self.data.loc[y.index, PREDICTORS].notna().all(axis=1)]
        sst = float(((y - y.mean()) ** 2).sum())
        sse, df = model["SSE"], int(model["Residual df"])
        close(model["R squared"], 1 - sse / sst)
        close(model["Adjusted R squared"], 1 - (sse / df) / (sst / (len(y) - 1)))
        f_value = (sst - sse) / 1 / (sse / df)
        close(model["F"], f_value)
        close(model["p"], stats.f.sf(f_value, 1, df))
        self.assertEqual(model["Confidence (%)"], 90.0)
        self.assertEqual(list(tables[MODEL].columns)[:12], [
            "PCA rows", "Regression rows", "Components", "Model df", "Residual df", "SSE", "MSE", "R squared",
            "Adjusted R squared", "F", "p", "Confidence (%)"])

    def test_full_rank_pcr_is_ordinary_least_squares_in_the_original_units(self):
        train = self.data.dropna(subset=PREDICTORS + ["Response"])
        x = np.column_stack((np.ones(len(train)), train[PREDICTORS].to_numpy()))
        ordinary = np.linalg.lstsq(x, train["Response"].to_numpy(), rcond=None)[0]
        covariance = (np.sum((train["Response"].to_numpy() - x @ ordinary) ** 2) / (len(train) - 3)
                      * np.linalg.inv(x.T @ x))
        for standardize in (False, True):
            with self.subTest(standardize=standardize):
                tables = run(self.data, standardize, **ON).tables
                close(tables[COEF]["Estimate"], ordinary)
                close(tables[COEF]["SE"], np.sqrt(np.diag(covariance)))
                self.assertEqual(tables[MODEL].iloc[0]["Components"], 2)

    def test_collinear_predictors_use_one_component_with_all(self):
        tables, want = self.check(fixture("rank"), True, None)
        self.assertEqual(want["count"], 1)
        self.assertEqual(list(tables[SCORES_COEF]["Term"]), ["Intercept", "PC1"])

    def test_score_coefficients_follow_the_reported_eigenvector_signs(self):
        tables = run(self.data, True, **ON, **FIXED_ONE).tables
        vector = tables["Eigenvectors"].loc[PREDICTORS, "PC1"].to_numpy()
        want = oracle(self.data, True, 1)
        sign = np.sign(vector @ want["basis"][:, 0])
        x = self.data[PREDICTORS].dropna().to_numpy()
        transformed = (x - x.mean(axis=0)) / x.std(axis=0, ddof=1)
        score = tables["Scores"]["PC1"].to_numpy()
        close(score, transformed @ vector)
        estimate = tables[SCORES_COEF]["Estimate"].to_numpy()
        # The slope on the score and the slope on the oracle component differ exactly by the sign.
        reference = np.linalg.lstsq(np.column_stack((np.ones(10), (score * sign)[:10])), self.data["Response"].iloc[:10],
                                    rcond=None)[0]
        close(estimate[1] * sign, reference[1])
        close(estimate[0], reference[0])

    def test_predictions_and_original_coefficients_do_not_depend_on_eigenvector_signs(self):
        base = run(self.data, True, **ON, Selection="All").tables
        real = exploration.pca

        def flipped(frame, columns, standardize=True):
            parts, vectors, scores = real(frame, columns, standardize)
            sign = np.array([-1.0, 1.0])
            return parts, vectors * sign, scores * sign

        with patch.object(exploration, "pca", flipped):
            other = run(self.data, True, **ON, Selection="All").tables
        close(other[COEF][RESULT], base[COEF][RESULT])
        close(other[FITTED].drop(columns="Source row").astype(float), base[FITTED].drop(columns="Source row").astype(float))
        close(other[SCORES_COEF]["Estimate"], base[SCORES_COEF]["Estimate"] * np.array([1.0, -1.0, 1.0]))
        close(other[SCORES_COEF]["SE"], base[SCORES_COEF]["SE"])
        close(other[SCORES_COEF]["Lower"], np.array([base[SCORES_COEF]["Lower"][0], -base[SCORES_COEF]["Upper"][1],
                                                     base[SCORES_COEF]["Lower"][2]]))

    def test_scores_sheet_names_follow_the_selection(self):
        cases = ((FIXED_ONE, ["PC1"]), ({"Selection": "Eigenvalue threshold", "Eigenvalue threshold": 1.0}, ["PC1"]),
                 ({"Selection": "Eigenvalue threshold", "Eigenvalue threshold": 0.1}, ["PC1", "PC2"]),
                 ({"Selection": "Cumulative variance", "Cumulative variance (%)": 99.0}, ["PC1", "PC2"]),
                 ({"Selection": "All"}, ["PC1", "PC2"]))
        for selection, names in cases:
            with self.subTest(selection):
                tables = run(self.data, True, **ON, **selection).tables
                self.assertEqual(list(tables[SCORES_COEF]["Term"]), ["Intercept", *names])
                self.assertEqual(tables[MODEL].iloc[0]["Components"], len(names))
                self.assertEqual(tables[MODEL].iloc[0]["Model df"], len(names))

    def test_parallel_selection_keeps_the_worker_budget_and_the_sheet_order(self):
        frame = fixture("main")
        selection = {"Selection": "Parallel analysis", "Parallel simulations": 10, "Parallel seed": 3,
                     "Parallel percentile (%)": 95.0}
        tables = run(frame, True, **ON, **selection).tables
        retained = tables[pca_retention.SELECTION_SHEET]["Retained"].tolist()
        self.assertEqual(tables[MODEL].iloc[0]["Components"], sum(retained))
        names = list(tables)
        self.assertLess(names.index(pca_retention.SELECTION_SHEET), names.index(COEF))

    def test_confidence_level_changes_only_the_widths(self):
        low = run(self.data, True, **{**ON, CONFIDENCE: 80}, **FIXED_ONE).tables
        high = run(self.data, True, **{**ON, CONFIDENCE: "99,5"}, **FIXED_ONE).tables
        close(low[COEF]["Estimate"], high[COEF]["Estimate"])
        self.assertTrue((high[COEF]["Upper"] - high[COEF]["Lower"] > low[COEF]["Upper"] - low[COEF]["Lower"]).all())
        self.assertEqual(high[MODEL].iloc[0]["Confidence (%)"], 99.5)
        df = int(high[MODEL].iloc[0]["Residual df"])
        half = stats.t.ppf((100 + 99.5) / 200, df) * high[COEF]["SE"]
        close(high[COEF]["Upper"] - high[COEF]["Estimate"], half)

    def test_literal_names_text_index_and_non_consecutive_rows(self):
        frame = self.data.rename(columns={"Conductivity": "Conducibilità (µS)", "Temperature": "Temp. °C $",
                                          "Response": "Risposta €"})
        frame.index = ["riga è", "1", "1", "x y", "$", "ß", "A/B", "ü", "9", "10", "last", "missing"]
        tables = analyse(METHOD, frame, {"Variables": ["Conducibilità (µS)", "Temp. °C $"], "Standardize": True,
                                         "Selection": "All", **ON, RESPONSE: "Risposta €"}).tables
        self.assertEqual(list(tables[COEF]["Term"]), ["Intercept", "Conducibilità (µS)", "Temp. °C $"])
        self.assertEqual(list(tables[FITTED]["Source row"]),
                         ["riga è", "1", "1", "x y", "$", "ß", "A/B", "ü", "9", "10", "last"])
        spaced = frame.copy()
        spaced.index = [5, 3, 3, 99, 7, 7, 1, 0, 2, 2, 8, 4]
        again = analyse(METHOD, spaced, {"Variables": ["Conducibilità (µS)", "Temp. °C $"], "Standardize": True,
                                         "Selection": "All", **ON, RESPONSE: "Risposta €"}).tables
        self.assertEqual(list(again[FITTED]["Source row"]), [5, 3, 3, 99, 7, 7, 1, 0, 2, 2, 8])
        close(again[FITTED].drop(columns="Source row").astype(float), tables[FITTED].drop(columns="Source row").astype(float))

    def test_duplicate_index_never_duplicates_scores_or_fitted_rows(self):
        frame = self.data.copy()
        labels = frame.index.tolist()
        labels[2] = labels[1]
        labels[5] = labels[1]
        frame.index = labels
        tables = run(frame, True, **ON, **FIXED_ONE).tables
        self.assertEqual(len(tables["Scores"]), 11)
        self.assertEqual(len(tables[FITTED]), 11)
        close(tables[FITTED]["Fitted"], oracle(frame, True, 1)["mean"])
        plain = run(self.data, True, **ON, **FIXED_ONE).tables
        close(tables[COEF][RESULT], plain[COEF][RESULT])

    def test_projection_uses_the_row_without_a_response_and_the_response_does_not_enter_the_pca(self):
        base = run(self.data, True, **ON, **FIXED_ONE).tables
        moved = self.data.copy()
        moved.loc["prediction only", "Temperature"] = 40.0
        after_x = run(moved, True, **ON, **FIXED_ONE).tables
        self.assertFalse(np.allclose(base["Explained variance"]["Eigenvalue"], after_x["Explained variance"]["Eigenvalue"]))
        self.assertFalse(np.allclose(base[COEF]["Estimate"], after_x[COEF]["Estimate"]))
        changed = self.data.copy()
        changed.loc["R04", "Response"] += 2.25
        after_y = run(changed, True, **ON, **FIXED_ONE).tables
        for name in ("Explained variance", "Eigenvectors", "Scores"):
            pd.testing.assert_frame_equal(base[name], after_y[name])
        self.assertFalse(np.allclose(base[COEF]["Estimate"], after_y[COEF]["Estimate"]))

    def test_excluded_response_and_excluded_predictor_follow_their_own_masks(self):
        excluded_response = self.data.copy()
        excluded_response.loc["R05", "Response"] = np.nan
        tables = run(excluded_response, True, **ON, **FIXED_ONE).tables
        row = tables[FITTED].set_index("Source row").loc["R05"]
        self.assertFalse(row["Used in fit"])
        self.assertTrue(np.isnan(row["Observed"]) and np.isnan(row["Residual"]) and np.isfinite(row["Fitted"]))
        self.assertEqual(tables[MODEL].iloc[0][["PCA rows", "Regression rows"]].tolist(), [11, 9])
        self.assertIn("R05", list(tables["Scores"].index))
        excluded_predictor = self.data.copy()
        excluded_predictor.loc["R06", "Temperature"] = np.nan
        tables = run(excluded_predictor, True, **ON, **FIXED_ONE).tables
        self.assertNotIn("R06", list(tables[FITTED]["Source row"]))
        self.assertEqual(tables[MODEL].iloc[0][["PCA rows", "Regression rows"]].tolist(), [10, 9])
        close(tables[FITTED]["Fitted"], oracle(excluded_predictor, True, 1)["mean"])

    def test_pca_rows_are_estimated_once_per_dispatch(self):
        selections = ({"Selection": "All"}, FIXED_ONE,
                      {"Selection": "Parallel analysis", "Parallel simulations": 10, "Parallel seed": 1,
                       "Parallel percentile (%)": 90.0})
        for graph in ({}, {pca_graphs.GRAPH: pca_graphs.SCORES}, {pca_graphs.GRAPH: pca_graphs.SCREE,
                                                                  **dict.fromkeys(pca_reports.OPTIONS, True)}):
            for selection in selections:
                with self.subTest(graph=graph, selection=selection):
                    real = exploration.pca
                    with patch.object(exploration, "pca", wraps=real) as engine:
                        run(self.data, True, **ON, **selection, **graph)
                    self.assertEqual(engine.call_count, 1)

    def test_numerical_fit_matches_the_prediction_for_a_response_made_of_scores(self):
        tables = run(self.data, True, **ON).tables
        known = self.data.assign(Response=2.0 - 0.5 * self.data["Conductivity"] + 4.0 * self.data["Temperature"])
        exact = run(known, True, **ON).tables
        close(exact[COEF]["Estimate"], [2.0, -0.5, 4.0])
        self.assertEqual(exact[MODEL].iloc[0]["SSE"], 0.0)
        self.assertEqual(exact[MODEL].iloc[0]["MSE"], 0.0)
        self.assertTrue(np.isinf(exact[MODEL].iloc[0]["F"]))
        self.assertEqual(exact[MODEL].iloc[0]["p"], 0.0)
        self.assertEqual(exact[MODEL].iloc[0]["R squared"], 1.0)
        for name in (COEF, SCORES_COEF):
            self.assertTrue((exact[name]["SE"] == 0).all())
            self.assertTrue(exact[name]["t"].isna().all() and exact[name]["p"].isna().all())
            close(exact[name]["Lower"], exact[name]["Estimate"])
            close(exact[name]["Upper"], exact[name]["Estimate"])
        rows = exact[FITTED]
        self.assertTrue((rows["Prediction lower"] == rows["Fitted"]).all() and (rows["Mean upper"] == rows["Fitted"]).all())
        self.assertFalse(tables[COEF]["SE"].eq(0).any())

    def test_constant_response_has_no_r_squared_f_or_p(self):
        constant = self.data.copy()
        constant.loc[constant["Response"].notna(), "Response"] = 0.1
        model = run(constant, True, **ON).tables[MODEL].iloc[0]
        for name in ("R squared", "Adjusted R squared", "F", "p"):
            self.assertTrue(np.isnan(model[name]), name)
        close(run(constant, True, **ON).tables[FITTED]["Fitted"], np.full(11, 0.1))

    def test_large_response_origin_keeps_measurable_residuals(self):
        x = np.arange(-4., 5.)
        other = np.array([-1, 1, 1, -1, 0, -1, 1, 1, -1], dtype=float)
        noise = np.array([-1, -1, 0, 1, 2, 1, 0, -1, -1], dtype=float)
        shifted = 1e12 + 2 * x + .004 * noise
        relative = shifted - 1e12
        design = np.column_stack((np.ones(len(x)), x, other))
        residuals = relative - design @ np.linalg.lstsq(design, relative, rcond=None)[0]
        frame = pd.DataFrame({PREDICTORS[0]: x, PREDICTORS[1]: other, "Response": shifted})

        result = run(frame, False, **ON).tables

        np.testing.assert_allclose(result[FITTED]["Residual"], residuals, atol=1e-12, rtol=1e-10)
        self.assertAlmostEqual(result[MODEL].loc[0, "SSE"], residuals @ residuals, places=14)
        self.assertTrue((result[FITTED]["Prediction upper"] > result[FITTED]["Prediction lower"]).all())


class PlotTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture("main")

    def view(self, plot, **extra):
        return run(self.data, True, **{**ON, PLOT: plot}, **FIXED_ONE, **extra)

    def test_observed_and_residual_plots_use_only_the_rows_of_the_fit(self):
        for plot, column in ((pca_regression.OBSERVED, "Observed"), (pca_regression.RESIDUALS, "Residual")):
            with self.subTest(plot):
                result = self.view(plot)
                axes = result.figure.axes[0]
                rows = result.tables[FITTED]
                used = rows[rows["Used in fit"]]
                self.assertEqual(len(axes.collections), 1)
                close(axes.collections[0].get_offsets(), np.column_stack((used["Fitted"], used[column])))
                self.assertEqual(axes.get_title(), plot)
                self.assertEqual(axes.get_xlabel(), "Fitted")
                self.assertEqual(axes.get_ylabel(), column)
                if column == "Observed":
                    self.assertTrue(any(np.array_equal(line.get_xdata(), line.get_ydata()) for line in axes.lines))
                else:
                    self.assertTrue(any(np.all(np.asarray(line.get_ydata()) == 0) for line in axes.lines))

    def test_keep_pca_leaves_the_pca_figure_alone(self):
        view = {pca_graphs.GRAPH: pca_graphs.SCORES, "PCA overlay": "Confidence region of mean",
                pca_reports.INPUT: True}
        base = run(self.data, True, Selection="All", **view)
        kept = run(self.data, True, Selection="All", **view, **ON)
        a, b = base.figure.axes[0], kept.figure.axes[0]
        self.assertEqual((a.get_title(), a.get_xlabel(), a.get_ylabel()), (b.get_title(), b.get_xlabel(), b.get_ylabel()))
        close(a.collections[0].get_offsets(), b.collections[0].get_offsets())
        close(a.patches[0].get_xy(), b.patches[0].get_xy())
        for name in ("Confidence overlays", pca_reports.INPUT_SHEET):
            pd.testing.assert_frame_equal(base.tables[name], kept.tables[name])
        self.assertIn(FITTED, kept.tables)

    def test_plot_replaces_every_pca_view_including_the_flat_ones_and_the_legacy_branch(self):
        for graph in ({}, {pca_graphs.GRAPH: pca_graphs.BIPLOT}, {pca_graphs.GRAPH: pca_graphs.SCREE}):
            with self.subTest(graph=graph):
                result = self.view("Observed vs fitted", **graph)
                self.assertEqual(result.figure.axes[0].get_title(), "Observed vs fitted")
                self.assertIn("Explained variance", result.tables)
                self.assertIn(FITTED, result.tables)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture("main")

    def same(self, before, after, *, extra=()):
        self.assertEqual([*before.tables, *extra], list(after.tables))
        for name in before.tables:
            pd.testing.assert_frame_equal(before.tables[name], after.tables[name])
        a, b = before.figure.axes[0], after.figure.axes[0]
        self.assertEqual(a.get_title(), b.get_title())
        self.assertEqual((a.get_xlabel(), a.get_ylabel()), (b.get_xlabel(), b.get_ylabel()))
        for u, v in zip(a.collections, b.collections, strict=True):
            close(u.get_offsets(), v.get_offsets())
        legend_a, legend_b = a.get_legend(), b.get_legend()
        self.assertEqual(legend_a is None, legend_b is None)
        if legend_a is not None:
            self.assertEqual([t.get_text() for t in legend_a.get_texts()], [t.get_text() for t in legend_b.get_texts()])

    def test_off_equals_absent_for_every_view_report_and_branch(self):
        stale = {RESPONSE: "not a column", CONFIDENCE: 100, PLOT: "nonsense"}
        reports = dict.fromkeys(pca_reports.OPTIONS, True)
        branches = ({}, {pca_graphs.GRAPH: pca_graphs.SCORES, "Color groups by": "Cohort"},
                    {pca_graphs.GRAPH: pca_graphs.BIPLOT, "Color groups by": "Cohort", **reports},
                    {pca_graphs.GRAPH: pca_graphs.SCREE, **reports},
                    {**FIXED_ONE, pca_graphs.GRAPH: pca_graphs.SCORES, **reports})
        for extra in branches:
            with self.subTest(extra=extra):
                before = run(self.data, True, **extra)
                self.same(before, run(self.data, True, **{**extra, ENABLE: False, **stale}))
                self.same(before, run(self.data, True, **{**extra, **stale}))
                self.assertFalse(set(pca_regression.SHEETS) & set(before.tables))

    def test_regression_adds_sheets_after_the_pca_output_and_keeps_the_rest(self):
        reports = dict.fromkeys(pca_reports.OPTIONS, True)
        extra = {pca_graphs.GRAPH: pca_graphs.SCORES, "Color groups by": "Cohort", **reports}
        before = run(self.data, True, **FIXED_ONE, **extra)
        after = run(self.data, True, **FIXED_ONE, **ON, **extra)
        self.same(before, after, extra=(COEF, SCORES_COEF, MODEL, FITTED))

    def test_the_four_new_options_are_registered_with_their_defaults(self):
        method = METHODS[METHOD]
        self.assertIs(method[ENABLE], False)
        self.assertEqual(method[CONFIDENCE], 95.0)
        self.assertEqual(method[PLOT], ("Keep PCA", "Observed vs fitted", "Residuals vs fitted"))
        self.assertIn(RESPONSE, method)
        self.assertEqual(list(pca_regression.TABS), ["Regression"])

    def test_the_dialog_probe_leaves_the_regression_to_the_real_selection(self):
        frame = fixture("rank")
        # With every living component the response loses rank on this table; the probe must not run the regression.
        pca_graphs.validate(frame, {**options(True), pca_graphs.GRAPH: pca_graphs.SCREE, "Selection": "Parallel analysis",
                                    "Parallel simulations": 10, **ON, RESPONSE: "Response"})


class FieldErrorTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture("main")

    def field(self, expected, frame=None, standardize=True, **extra):
        with self.assertRaises(FieldError) as caught:
            run(self.data if frame is None else frame, standardize, **{**ON, **extra})
        self.assertEqual(caught.exception.field, expected, str(caught.exception))
        return str(caught.exception)

    def test_response_choices(self):
        self.field(RESPONSE, **{RESPONSE: None})
        self.field(RESPONSE, **{RESPONSE: ""})
        self.field(RESPONSE, **{RESPONSE: "Absent"})
        self.field(RESPONSE, **{RESPONSE: "Temperature"})
        self.assertIn("not one of the PCA variables", self.field(RESPONSE, **{RESPONSE: "Conductivity"}))

    def test_confidence_must_be_finite_and_strictly_between_zero_and_one_hundred(self):
        for bad in (100, 0, -5, 100.5, float("nan"), float("inf"), "100", "0", "abc", "", None, True, "9,x"):
            with self.subTest(bad=bad):
                self.field(CONFIDENCE, **{CONFIDENCE: bad})
        for good in (90, 90.5, "90,5", "99.9", 0.001):
            with self.subTest(good=good):
                shown = run(self.data, True, **{**ON, CONFIDENCE: good}, **FIXED_ONE).tables[MODEL].iloc[0]
                self.assertEqual(shown["Confidence (%)"], float(str(good).replace(",", ".")))

    def test_unknown_plot_and_non_boolean_switch(self):
        self.field(PLOT, **{PLOT: "Scores"})
        self.field(ENABLE, **{ENABLE: "yes"})
        self.field(ENABLE, **{ENABLE: 1})
        run(self.data, True, **{**ON, PLOT: ""}, **FIXED_ONE)
        run(self.data, True, **{**ON, PLOT: None}, **FIXED_ONE)

    def test_zero_components_report_the_selection_field(self):
        message = self.field("Selection", Selection="Eigenvalue threshold", **{"Eigenvalue threshold": 10000})
        self.assertIn("no components", message)

    def test_degrees_of_freedom_and_rank_name_the_response(self):
        few = self.data.copy()
        few.iloc[2:, few.columns.get_loc("Response")] = np.nan
        self.assertIn("more than 2 rows", self.field(RESPONSE, few, **FIXED_ONE))
        self.assertIn("lose rank", self.field(RESPONSE, fixture("response-rank"), Selection="All"))
        none = self.data.assign(Response=np.nan)
        self.field(RESPONSE, none, Selection="All")

    def test_a_subset_with_enough_rank_for_fewer_components_still_runs(self):
        tables = run(fixture("response-rank"), True, **ON, **FIXED_ONE).tables
        self.assertEqual(tables[MODEL].iloc[0]["Regression rows"], 5)

    def test_text_or_infinite_response_on_a_usable_row_is_a_response_error(self):
        text = self.data.assign(Response=self.data["Response"].astype(object))
        text.loc["R02", "Response"] = "invalid"
        self.assertIn("row 2", self.field(RESPONSE, text, **FIXED_ONE))
        infinite = self.data.copy()
        infinite.loc["R03", "Response"] = np.inf
        self.field(RESPONSE, infinite, **FIXED_ONE)
        blank = self.data.assign(Response=self.data["Response"].astype(object))
        blank.loc["R02", "Response"] = None
        self.assertEqual(run(blank, True, **ON, **FIXED_ONE).tables[MODEL].iloc[0]["Regression rows"], 9)

    def test_text_in_a_row_without_complete_predictors_is_not_a_response_error(self):
        text = self.data.assign(Response=self.data["Response"].astype(object))
        text.loc["missing X", "Response"] = "not measured"
        tables = run(text, True, **ON, **FIXED_ONE).tables
        close(tables[COEF]["Estimate"], oracle(self.data, True, 1)["raw"][:, 0])

    def test_values_beyond_the_numeric_domain_are_an_explicit_error(self):
        huge = self.data.copy()
        huge["Response"] = huge["Response"] * 1e200
        huge.loc["R02", "Response"] = 1e308
        self.field(RESPONSE, huge, **FIXED_ONE)

    def test_a_response_chosen_among_the_predictors_fails_before_any_estimation(self):
        with patch.object(exploration, "pca") as engine:
            with self.assertRaises(FieldError):
                run(self.data, True, **{**ON, RESPONSE: "Temperature"})
        engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
