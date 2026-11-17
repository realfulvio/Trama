"""Compare models (AICc): formulas, ranking order, unavailable rows and the dispatcher contract."""
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi import model_selection as ms
from analisi.processing import FieldError
from analisi.workbench import METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "model_selection"
METHOD = ms.COMPARE_MODELS
THREE = ["Horizontal line", "Straight line", "Polynomial (order 2)"]


def options(models=THREE, **extra):
    return {"X": "X", "Y": "Y", "Group": None, "Models": list(models), "Show graph": True, **extra}


def aicc_frame():
    return pd.read_csv(DATA / "aicc.csv")


def by_model(result):
    return result.tables[ms.RANKING].set_index("Model")


def analytic(x, y, degree):
    """Independent least-squares fit: RSS and the corrected criterion."""
    design = np.vander(x, degree + 1, increasing=True)
    residual = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    rss, n, k = float(residual @ residual), len(y), degree + 2
    return rss, n * np.log(rss / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1)


class Formulas(unittest.TestCase):
    def test_rss_aicc_and_weights_follow_the_formulas(self):
        frame = aicc_frame()
        ranking = by_model(analyse(METHOD, frame, options()))
        scores = []
        for degree, model in enumerate(THREE):
            rss, score = analytic(frame.X.to_numpy(), frame.Y.to_numpy(), degree)
            row = ranking.loc[model]
            self.assertEqual((row["N"], row["Parameters"], row["K"]), (12, degree + 1, degree + 2))
            np.testing.assert_allclose([row["RSS"], row["AICc"]], [rss, score], rtol=2e-6)
            np.testing.assert_allclose(row["AIC"], row["AICc"] - 2 * row["K"] * (row["K"] + 1) / (12 - row["K"] - 1))
            self.assertEqual(row["Status"], "OK")
            scores.append(score)
        delta = np.array(scores) - min(scores)
        weights = np.exp(-delta / 2) / np.exp(-delta / 2).sum()
        np.testing.assert_allclose(ranking.loc[THREE, "Akaike weight"], weights, rtol=2e-6)
        np.testing.assert_allclose(ranking.loc[THREE, "Delta AICc"], delta, atol=1e-9)
        self.assertAlmostEqual(ranking["Akaike weight"].sum(), 1, delta=1e-12)

    def test_sheets_and_columns_are_canonical(self):
        result = analyse(METHOD, aicc_frame(), options())
        self.assertEqual(list(result.tables), ["Model ranking", "Model parameters", "Summary"])
        self.assertEqual(list(result.tables["Model ranking"].columns), [
            "Group", "Model", "N", "Parameters", "K", "RSS", "AIC", "AICc", "Delta AICc", "Akaike weight", "Status"])
        self.assertEqual(list(result.tables["Model parameters"].columns),
                         ["Group", "Model", "Parameter", "Estimate", "SE"])
        self.assertEqual(list(result.tables["Summary"].columns), ["Group", "Best model", "Valid models", "Note"])
        summary = result.tables["Summary"].iloc[0]
        self.assertEqual((summary["Group"], summary["Best model"], summary["Valid models"]), ("All", "Straight line", 3))

    def test_ranking_is_by_aicc_and_parameters_are_reported(self):
        result = analyse(METHOD, aicc_frame(), options())
        ranking = result.tables[ms.RANKING]
        self.assertEqual(ranking["Model"].tolist(), ["Straight line", "Polynomial (order 2)", "Horizontal line"])
        self.assertTrue(ranking["AICc"].is_monotonic_increasing)
        parameters = result.tables[ms.PARAMETERS].set_index(["Model", "Parameter"])
        self.assertAlmostEqual(parameters.loc[("Straight line", "Intercept"), "Estimate"], 5.0, places=6)
        self.assertAlmostEqual(parameters.loc[("Straight line", "Slope"), "Estimate"], 2.0, places=6)
        self.assertEqual(len(parameters), 6)
        self.assertTrue(np.isfinite(parameters["SE"]).all())

    def test_scaling_y_keeps_delta_and_weights(self):
        frame = aicc_frame()
        scaled = frame.assign(Y=frame.Y * 100)
        first, second = (by_model(analyse(METHOD, data, options())) for data in (frame, scaled))
        np.testing.assert_allclose(second.loc[THREE, "Akaike weight"], first.loc[THREE, "Akaike weight"], rtol=2e-6)
        np.testing.assert_allclose(second.loc[THREE, "Delta AICc"], first.loc[THREE, "Delta AICc"], rtol=2e-6, atol=1e-7)

    def test_weights_do_not_overflow_for_huge_differences(self):
        delta, weights = ms.akaike_weights([1e9, 1e9 + 4e3, 1e9 + 2e5, 1e9 + 1e7])
        np.testing.assert_allclose(delta, [0, 4e3, 2e5, 1e7])
        self.assertTrue(np.isfinite(weights).all())
        self.assertAlmostEqual(weights.sum(), 1, delta=1e-12)
        self.assertEqual(weights[0], 1.0)

    def test_criteria_helper_reasons(self):
        aic, aicc, status = ms.criteria(2.0, 10, 2, 50.)
        self.assertEqual(status, "OK")
        self.assertAlmostEqual(aic, 10 * np.log(.2) + 6)
        self.assertAlmostEqual(aicc, aic + 2 * 3 * 4 / 6)
        aic, aicc, status = ms.criteria(2.0, 4, 2, 50.)  # K = 3, N = K + 1
        self.assertTrue(np.isfinite(aic) and np.isnan(aicc) and "greater than K + 1" in status, status)
        for rss in (0., 1e-20, np.nan, np.inf):
            aic, aicc, status = ms.criteria(rss, 10, 2, 50.)
            self.assertTrue(np.isnan(aic) and np.isnan(aicc) and status != "OK", (rss, status))


class UnavailableRows(unittest.TestCase):
    def test_small_sample_leaves_the_corrected_criterion_unavailable(self):
        frame = aicc_frame().iloc[:4]
        result = analyse(METHOD, frame, options())
        ranking = by_model(result)
        self.assertTrue(np.isfinite(ranking.loc["Horizontal line", "AICc"]))
        for model in ("Straight line", "Polynomial (order 2)"):
            self.assertTrue(np.isnan(ranking.loc[model, "AICc"]), model)
            self.assertNotEqual(ranking.loc[model, "Status"], "OK")
        self.assertEqual(result.tables[ms.RANKING]["Model"].iloc[0], "Horizontal line")
        summary = result.tables[ms.SUMMARY].iloc[0]
        self.assertEqual(summary["Valid models"], 1)
        self.assertTrue(pd.isna(summary["Best model"]))
        self.assertIn("unavailable", summary["Note"])
        self.assertTrue(ranking[["Delta AICc", "Akaike weight"]].isna().all().all())
        self.assertIsNotNone(result.figure)
        self.assertGreater(len(result.tables[ms.PARAMETERS]), 0, "fits stay available")

    def test_perfect_fit_is_unavailable_with_a_reason(self):
        frame = pd.DataFrame({"X": range(6), "Y": [1, 3, 5, 7, 9, 11]})
        result = analyse(METHOD, frame, options(["Horizontal line", "Straight line"]))
        ranking = by_model(result)
        self.assertIn("Perfect fit", ranking.loc["Straight line", "Status"])
        self.assertTrue(np.isnan(ranking.loc["Straight line", ["AIC", "AICc"]]).all())
        self.assertEqual(result.tables[ms.RANKING]["Model"].tolist(), ["Horizontal line", "Straight line"])
        self.assertEqual(result.tables[ms.SUMMARY]["Valid models"].iloc[0], 1)

    def test_domain_error_keeps_the_other_candidates(self):
        x = np.array([-3., -2, -1, 0, 1, 2, 3, 4])
        frame = pd.DataFrame({"X": x, "Y": 2 + .5 * x + .3 * x**2 + np.array([.2, -.1, .15, -.2, .1, -.15, .05, -.05])})
        result = analyse(METHOD, frame, options(["Michaelis–Menten", "Straight line", "Polynomial (order 2)"]))
        ranking = by_model(result)
        self.assertIn("nonnegative", ranking.loc["Michaelis–Menten", "Status"])
        self.assertTrue(np.isnan(ranking.loc["Michaelis–Menten", "AICc"]))
        valid = ranking.loc[["Straight line", "Polynomial (order 2)"]]
        self.assertEqual(valid["Status"].tolist(), ["OK", "OK"])
        self.assertAlmostEqual(valid["Akaike weight"].sum(), 1, delta=1e-12)
        self.assertEqual(result.tables[ms.RANKING]["Model"].iloc[-1], "Michaelis–Menten")
        self.assertEqual(result.tables[ms.SUMMARY]["Valid models"].iloc[0], 2)
        self.assertEqual(result.tables[ms.SUMMARY]["Best model"].iloc[0], "Polynomial (order 2)")
        self.assertNotIn("Michaelis–Menten", result.tables[ms.PARAMETERS]["Model"].tolist())
        legend = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(legend, ["Observations", "Straight line", "Polynomial (order 2)"])

    def test_unavailable_rows_follow_in_selection_order(self):
        x = np.array([-3., -2, -1, 0, 1, 2, 3, 4])
        frame = pd.DataFrame({"X": x, "Y": 2 + .5 * x + .3 * x**2 + np.array([.2, -.1, .15, -.2, .1, -.15, .05, -.05])})
        models = ["One-site specific binding", "Straight line", "Michaelis–Menten", "Polynomial (order 2)"]
        ranking = analyse(METHOD, frame, options(models)).tables[ms.RANKING]
        self.assertEqual(ranking["Model"].tolist()[2:], ["One-site specific binding", "Michaelis–Menten"])


class Ties(unittest.TestCase):
    def test_equal_criteria_keep_the_selection_order(self):
        frame = aicc_frame()
        for models in (["Straight line", "Polynomial (order 1)", "Horizontal line"],
                       ["Polynomial (order 1)", "Straight line", "Horizontal line"]):
            ranking = analyse(METHOD, frame, options(models)).tables[ms.RANKING]
            self.assertEqual(ranking["Model"].tolist(), models[:2] + ["Horizontal line"])
            np.testing.assert_allclose(ranking["Akaike weight"].iloc[0], ranking["Akaike weight"].iloc[1], rtol=1e-9)

    def test_rank_helper_orders_ties_by_position(self):
        rows = [ms.Candidate(name, i, 2, aicc=value) for i, (name, value) in
                enumerate([("a", 10.0), ("b", 5.0), ("c", 5.0 + 1e-12), ("d", 5.0)])]
        self.assertEqual([c.model for c in ms.rank(rows)], ["b", "c", "d", "a"])


class Missing(unittest.TestCase):
    def test_every_candidate_uses_the_same_complete_rows(self):
        frame = aicc_frame()
        frame.loc[[2, 7], "Y"] = np.nan
        frame.loc[4, "X"] = np.nan
        frame["Note"] = "text"
        result = analyse(METHOD, frame, options())
        ranking = result.tables[ms.RANKING]
        self.assertEqual(ranking["N"].tolist(), [9] * 3)
        clean = frame.dropna(subset=["X", "Y"])
        for model, degree in zip(THREE, range(3)):
            rss, _ = analytic(clean.X.to_numpy(), clean.Y.to_numpy(), degree)
            np.testing.assert_allclose(by_model(result).loc[model, "RSS"], rss, rtol=1e-6)

    def test_duplicate_index_labels_and_text_are_handled(self):
        frame = aicc_frame()
        frame.index = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
        frame.loc[3, "Y"] = np.nan
        frame["Y"] = frame["Y"].astype(object)
        frame.iloc[0, 1] = "-6.593255013631379"
        result = analyse(METHOD, frame, options())
        self.assertEqual(result.tables[ms.RANKING]["N"].tolist(), [10] * 3)

    def test_no_complete_rows_names_the_field(self):
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, pd.DataFrame({"X": [1., 2], "Y": [np.nan, np.nan]}), options(["Straight line", "Horizontal line"]))
        self.assertEqual(caught.exception.field, "X")


class Groups(unittest.TestCase):
    def frame(self):
        x = np.arange(1., 9)
        a = 2 + 3 * x + np.array([.4, -.3, .2, -.4, .3, -.2, .1, -.1])
        b = 20 - .5 * x**2 + 3 * x + np.array([.3, .2, -.4, .1, -.2, .3, -.1, .2])
        return pd.DataFrame({"X": np.r_[x, x], "Y": np.r_[a, b], "Grp": ["All"] * 8 + ["Ünï · A/B"] * 8})

    def test_groups_are_ranked_separately_with_literal_names(self):
        result = analyse(METHOD, self.frame(), options(Group="Grp"))
        ranking = result.tables[ms.RANKING]
        self.assertEqual(ranking["Group"].tolist(), ["All"] * 3 + ["Ünï · A/B"] * 3)
        for label, part in ranking.groupby("Group", sort=False):
            self.assertAlmostEqual(part["Akaike weight"].sum(), 1, delta=1e-12)
            self.assertTrue(part["AICc"].is_monotonic_increasing)
        summary = result.tables[ms.SUMMARY]
        self.assertEqual(summary["Group"].tolist(), ["All", "Ünï · A/B"])
        self.assertEqual(summary["Best model"].tolist(), ["Straight line", "Polynomial (order 2)"])
        self.assertEqual(len(result.figure.axes), 2)
        self.assertEqual([axes.get_title() for axes in result.figure.axes], ["All", "Ünï · A/B"])

    def test_group_with_few_observations_does_not_block_the_others(self):
        frame = self.frame()
        small = pd.DataFrame({"X": [1., 2], "Y": [3., 5], "Grp": ["tiny"] * 2})
        result = analyse(METHOD, pd.concat([frame, small], ignore_index=True), options(Group="Grp"))
        summary = result.tables[ms.SUMMARY].set_index("Group")
        self.assertEqual(summary.loc["tiny", "Valid models"], 0)
        self.assertTrue(pd.isna(summary.loc["tiny", "Best model"]))
        self.assertEqual(summary.loc["All", "Best model"], "Straight line")
        tiny = result.tables[ms.RANKING].query("Group == 'tiny'")
        self.assertTrue((tiny["Status"] != "OK").all())

    def test_numeric_and_missing_group_labels(self):
        frame = self.frame().assign(Grp=[1] * 8 + [2] * 6 + [np.nan] * 2)
        result = analyse(METHOD, frame, options(Group="Grp"))
        self.assertEqual(result.tables[ms.SUMMARY]["Group"].tolist(), ["1.0", "2.0"])
        self.assertEqual(result.tables[ms.RANKING].groupby("Group")["N"].first().tolist(), [8, 6])

    def test_group_must_differ_from_x_and_y(self):
        for column in ("X", "Y"):
            with self.assertRaises(FieldError) as caught:
                analyse(METHOD, self.frame(), options(Group=column))
            self.assertEqual(caught.exception.field, "Group")


class Validation(unittest.TestCase):
    def field(self, **extra):
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, aicc_frame(), options(**extra))
        return caught.exception

    def test_duplicate_selection_names_the_field(self):
        error = self.field(Models=["Straight line", "Straight line"])
        self.assertEqual(error.field, "Models")
        self.assertIn("more than once", str(error))

    def test_selection_size_and_catalog(self):
        self.assertEqual(self.field(Models=["Straight line"]).field, "Models")
        self.assertEqual(self.field(Models=[]).field, "Models")
        nine = [name for name in ms.CANDIDATES if name != "Horizontal line"][:9]
        self.assertEqual(self.field(Models=nine).field, "Models")
        self.assertEqual(self.field(Models=["Straight line", "Not a model"]).field, "Models")
        self.assertEqual(self.field(Models="Straight line").field, "Models")
        self.assertEqual(self.field(Models=None).field, "Models")
        shared = next(name for name, spec in ms.MODELS.items() if spec.required_shared or spec.required_fixed)
        self.assertIn("Global nonlinear regression", str(self.field(Models=["Straight line", shared])))
        eight = list(ms.CANDIDATES[:8])
        self.assertEqual(len(analyse(METHOD, aicc_frame(), options(eight)).tables[ms.SUMMARY]), 1)

    def test_columns_are_checked(self):
        self.assertEqual(self.field(X="Missing").field, "X")
        self.assertEqual(self.field(Y="X").field, "Y")
        self.assertEqual(self.field(Y=None).field, "Y")

    def test_show_graph_switch(self):
        self.assertIsNone(analyse(METHOD, aicc_frame(), options(**{"Show graph": False})).figure)
        legacy_like = {key: value for key, value in options().items() if key != "Show graph"}
        self.assertIsNotNone(analyse(METHOD, aicc_frame(), legacy_like).figure)
        self.assertEqual(self.field(**{"Show graph": "yes"}).field, "Show graph")

    def test_candidates_are_the_nonlinear_regression_list(self):
        listed = METHODS["Nonlinear regression"]["Model"]
        self.assertEqual(set(ms.CANDIDATES), set(listed))
        self.assertEqual(len(ms.CANDIDATES), len(set(ms.CANDIDATES)))


class Graph(unittest.TestCase):
    def test_points_and_curves_in_selection_order_without_a_second_fit(self):
        models = ["Polynomial (order 2)", "Horizontal line", "Straight line"]
        result = analyse(METHOD, aicc_frame(), options(models))
        axes = result.figure.axes[0]
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Observations", *models])
        self.assertEqual(len(axes.lines), 3)
        self.assertEqual(len(axes.collections), 1)
        self.assertEqual(axes.collections[0].get_offsets().shape, (12, 2))
        self.assertEqual([line.get_gid() for line in axes.lines], [f"model-selection:curve:All:{m}" for m in models])


class Legacy(unittest.TestCase):
    def test_f_test_sheet_is_unchanged(self):
        frame = pd.read_csv(DATA / "legacy-nested.csv")
        result = analyse("Compare nonlinear models", frame, {
            "X": "X", "Y": "Y", "Group": None, "Nested models": "One-site specific binding → One-site total binding",
            "Weighting": "Unweighted"})
        self.assertEqual(list(result.tables), ["Extra sum-of-squares F test"])
        table = result.tables["Extra sum-of-squares F test"]
        self.assertEqual(table.index.tolist(), ["All"])
        self.assertEqual(list(table.columns), ["Simple model", "Complex model", "Simple SS", "Complex SS",
                                               "df numerator", "df denominator", "F", "p"])
        row = table.iloc[0]
        self.assertEqual((row["df numerator"], row["df denominator"]), (2, 8))
        np.testing.assert_allclose([row["Simple SS"], row["Complex SS"], row["F"], row["p"]],
                                   [3.2918772963696212, 0.0018570303122397924, 7086.626953523959, 1.0127480518727257e-13],
                                   rtol=1e-8)
        self.assertIsNone(result.figure)

    def test_polynomial_start_ignores_rounding_noise_only(self):
        from analisi.curve_models import MODELS
        frame = aicc_frame()
        start = MODELS["Polynomial (order 2)"].initial(frame.X.to_numpy(), frame.Y.to_numpy())
        self.assertEqual(start[2], 0.0)
        np.testing.assert_allclose(start[:2], [5, 2], atol=1e-12)
        x = np.linspace(-2, 2, 9)
        y = 1 + .5 * x + 2 * x**2
        np.testing.assert_allclose(MODELS["Polynomial (order 2)"].initial(x, y), [1, .5, 2], atol=1e-12)
        tiny = MODELS["Polynomial (order 2)"].initial(x, 1e-9 * y)
        np.testing.assert_allclose(tiny, np.array([1, .5, 2]) * 1e-9, rtol=1e-8)


if __name__ == "__main__":
    unittest.main()
