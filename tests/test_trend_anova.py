"""Ordinal trend after ordinary one-way ANOVA."""
import unittest

import numpy as np
import pandas as pd

from analisi.processing import FieldError
from analisi.trend_anova import ORDER, TREND, group_levels, trend_tables


def _order(*labels):
    return [{"kind": "text", "value": label} for label in labels]


def _balanced(column="y"):
    groups = ("10", "10", "10", "1", "1", "1", "100", "100", "100", "3", "3", "3")
    values = [1, 2, 3, 3, 4, 5, 4, 5, 6, 8, 9, 10]
    return pd.DataFrame({"group": list(groups), column: values})


def _metrics(frame, order, response="y"):
    tables = trend_tables(frame, response, "group", order)
    return tables["Linear trend"]["Value"].to_dict(), tables["Trend group means"]


class TrendMathTests(unittest.TestCase):
    def test_balanced_matches_the_independent_oracle(self):
        metrics, means = _metrics(_balanced(), _order("10", "1", "100", "3"))
        self.assertEqual(metrics["N"], 12)
        self.assertEqual(metrics["Groups"], 4)
        self.assertAlmostEqual(metrics["Slope"], 2.2)
        self.assertAlmostEqual(metrics["Intercept"], -0.5)
        self.assertAlmostEqual(metrics["SS linear"], 72.6)
        self.assertAlmostEqual(metrics["SS nonlinear"], 5.4)
        self.assertAlmostEqual(metrics["SS within"], 8)
        self.assertAlmostEqual(metrics["F linear"], 72.6)
        self.assertAlmostEqual(metrics["p linear"], 2.7662610914284855e-05)
        self.assertAlmostEqual(metrics["F nonlinear"], 2.7)
        self.assertAlmostEqual(metrics["p nonlinear"], 0.12704007881248872)
        self.assertAlmostEqual(metrics["R² effect"], 0.8441860465116279)
        self.assertAlmostEqual(metrics["R² alerting"], 0.9307692307692308)
        self.assertIn("ordinal", metrics["Convention"].lower())
        self.assertEqual(means["Score"].tolist(), [1, 2, 3, 4])
        self.assertEqual(means["Group value"].tolist(), ["10", "1", "100", "3"])

    def test_linear_and_curved_means(self):
        linear = _balanced()
        linear["y"] = [1, 2, 3, 3, 4, 5, 5, 6, 7, 7, 8, 9]
        metrics, _ = _metrics(linear, _order("10", "1", "100", "3"))
        self.assertAlmostEqual(metrics["SS nonlinear"], 0)
        self.assertAlmostEqual(metrics["p nonlinear"], 1)
        curved = _balanced()
        curved["y"] = [1, 2, 3, 4, 5, 6, 4, 5, 6, 1, 2, 3]
        metrics, _ = _metrics(curved, _order("10", "1", "100", "3"))
        self.assertAlmostEqual(metrics["Slope"], 0)
        self.assertAlmostEqual(metrics["p linear"], 1)
        self.assertAlmostEqual(metrics["SS nonlinear"], 27)
        self.assertAlmostEqual(metrics["F nonlinear"], 13.5)

    def test_unbalanced_weights_and_reversal(self):
        frame = pd.DataFrame({
            "group": ["10", "10", "1", "1", "1", "100", "100", "100", "100", "3", "3", "3", "3", "3"],
            "y": [0.5, 1.5, 2, 3, 4, 2.5, 3.5, 4.5, 5.5, 6, 7, 8, 9, 10],
        })
        order = _order("10", "1", "100", "3")
        forward, _ = _metrics(frame, order)
        backward, means = _metrics(frame, list(reversed(order)))
        self.assertAlmostEqual(forward["Slope"], 2.327272727272727)
        self.assertAlmostEqual(forward["SS linear"], 85.11168831168831)
        self.assertAlmostEqual(backward["Slope"], -forward["Slope"])
        self.assertAlmostEqual(backward["Intercept"], forward["Intercept"] + forward["Slope"] * 5)
        for key in ("SS linear", "F linear", "p linear", "F nonlinear", "p nonlinear", "R² effect", "R² alerting"):
            self.assertAlmostEqual(backward[key], forward[key], msg=key)
        self.assertEqual(means["N"].tolist(), [5, 4, 3, 2])

    def test_two_and_three_groups_omit_the_nonlinear_p(self):
        frame = _balanced()
        for labels in (("10", "1"), ("10", "1", "100")):
            part = frame[frame.group.isin(labels)]
            metrics, _ = _metrics(part, _order(*labels))
            self.assertTrue(np.isnan(metrics["p nonlinear"]))
            self.assertTrue(np.isnan(metrics["F nonlinear"]))
            self.assertIn("four", metrics["Note"])

    def test_equal_means_keep_a_nonlinear_p_of_one(self):
        frame = _balanced()
        frame["y"] = [1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3]
        metrics, _ = _metrics(frame, _order("10", "1", "100", "3"))
        self.assertEqual(metrics["p linear"], 1)
        self.assertEqual(metrics["p nonlinear"], 1)
        self.assertEqual(metrics["R² effect"], 0)
        self.assertTrue(np.isnan(metrics["R² alerting"]))

    def test_single_observation_group_has_no_variance(self):
        frame = pd.DataFrame({"group": ["a", "a", "b", "c", "c"], "y": [1., 3, 2, 4, 6]})
        metrics, means = _metrics(frame, _order("a", "b", "c"))
        self.assertEqual(metrics["df within"], 2)
        self.assertTrue(np.isnan(means.loc[means["Group value"] == "b", "Variance"]).all())

    def test_offset_and_scale_keep_f_and_transform_the_line(self):
        base, _ = _metrics(_balanced(), _order("10", "1", "100", "3"))
        shifted = _balanced()
        shifted["y"] = shifted["y"] + 1e9
        offset, _ = _metrics(shifted, _order("10", "1", "100", "3"))
        scaled = _balanced()
        scaled["y"] = scaled["y"] * 1e-12
        tiny, _ = _metrics(scaled, _order("10", "1", "100", "3"))
        self.assertAlmostEqual(offset["Slope"], base["Slope"])
        self.assertAlmostEqual(offset["Intercept"], base["Intercept"] + 1e9)
        self.assertAlmostEqual(tiny["Slope"], base["Slope"] * 1e-12)
        self.assertAlmostEqual(tiny["Intercept"], base["Intercept"] * 1e-12)
        for metrics in (offset, tiny):
            self.assertAlmostEqual(metrics["F linear"], base["F linear"], places=6)
            self.assertAlmostEqual(metrics["p linear"], base["p linear"])
            self.assertAlmostEqual(metrics["p nonlinear"], base["p nonlinear"])

    def test_missing_and_excluded_rows_match_the_complete_cases(self):
        frame = _balanced()
        frame.loc[len(frame)] = ["10", np.nan]
        frame.loc[len(frame)] = ["new-level", np.nan]
        metrics, _ = _metrics(frame, _order("10", "1", "100", "3"))
        self.assertEqual(metrics["N"], 12)
        self.assertEqual(group_levels(frame, "y", "group")[-1]["value"], "3")

    def test_order_and_identity_errors_name_their_field(self):
        frame = _balanced()
        order = _order("10", "1", "100", "3")
        typed = pd.DataFrame({"group": [1, 1, 1, "1", "1", "1", 2, 2, 2, "2", "2", "2"],
                              "y": [1, 2, 3, 3, 4, 5, 4, 5, 6, 8, 9, 10]})
        typed_order = [{"kind": "number", "value": 1}, {"kind": "text", "value": "1"},
                       {"kind": "number", "value": 2}, {"kind": "text", "value": "2"}]
        _, means = _metrics(typed, typed_order)
        self.assertEqual(means["Group kind"].tolist(), ["number", "text", "number", "text"])
        self.assertEqual(means["Group value"].tolist(), [1, "1", 2, "2"])
        self.assertIn("[", means["Group label"].iloc[0])
        flags = pd.DataFrame({"group": [True, True, False, False], "y": [1., 2, 3, 4]})
        with self.assertRaises(FieldError) as caught:
            trend_tables(flags, "y", "group", [{"kind": "text", "value": "True"}])
        self.assertEqual(caught.exception.field, TREND)
        for bad in (order[:-1], order + order[:1], order[:-1] + [{"kind": "text", "value": "absent"}],
                    ["10", "1", "100", "3"]):
            with self.assertRaises(FieldError) as caught:
                trend_tables(frame, "y", "group", bad)
            self.assertEqual(caught.exception.field, ORDER)
        original = frame.copy(deep=True)
        trend_tables(frame, "y", "group", order)
        pd.testing.assert_frame_equal(frame, original)

    def test_zero_pooled_variance_is_a_trend_error(self):
        frame = _balanced()
        frame["y"] = 1.0
        with self.assertRaises(FieldError) as caught:
            trend_tables(frame, "y", "group", _order("10", "1", "100", "3"))
        self.assertEqual(caught.exception.field, TREND)


if __name__ == "__main__":
    unittest.main()
