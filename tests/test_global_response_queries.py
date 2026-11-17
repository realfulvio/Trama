"""Global fit custom equation, 0.70: predictions for new X assigned to a series.

Interval numbers come from the independent oracles in tests/data/global_uncertainty/expected.json.
"""
import copy
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi import global_custom_fit as engine
from analisi import global_uncertainty as uncertainty
from analisi.field_error import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "global_uncertainty"
RECIPES = json.loads((DATA / "recipes.json").read_text())
EXPECTED = json.loads((DATA / "expected.json").read_text())
METHOD = engine.GLOBAL_CUSTOM_EQUATION


def frame(name):
    return pd.DataFrame(json.loads((DATA / f"{name}.json").read_text()))


def recipe(name, **more):
    options = copy.deepcopy(RECIPES[name])
    options.update({"Response level (%)": 90., "Predict responses": True, "Query X": "Query X",
                    "Query group": "Query group", "Query replicate count": "Query k", "Query interval": "Prediction",
                    "Allow extrapolation": False})
    options.update(more)
    return options


def predictions(name, data=None, **more):
    result = analyse(METHOD, frame(name) if data is None else data, recipe(name, **more))
    return result, result.tables["Predictions"]


class Numbers(unittest.TestCase):
    def test_against_oracles_for_every_interval(self):
        for name in ("linear-shared", "linear-fixed", "linear-small-y", "linear-empty-label",
                     "decay-shared", "decay-large-x"):
            for interval in ("Confidence", "Prediction"):
                _, table = predictions(name, **{"Query interval": interval, "Allow extrapolation": True})
                for reference in EXPECTED[name]["queries"]:
                    row = table[table["Source row"] == reference["Source row"]].iloc[0]
                    status = "Extrapolated" if reference["Status"] == "Outside domain" else reference["Status"]
                    with self.subTest(case=name, interval=interval, row=reference["Source row"]):
                        self.assertEqual(row["Status"], status)
                        if status not in ("OK", "Extrapolated"):
                            continue
                        expected = [reference["Predicted"], reference["SE mean"],
                                    reference[f"{interval} lower"], reference[f"{interval} upper"]]
                        np.testing.assert_allclose(row[["Predicted", "SE mean", "Lower", "Upper"]].to_numpy(float),
                                                   expected, rtol=3e-6, atol=0)
                        self.assertEqual(row["Level"], 90.)
                        if interval == "Prediction":
                            self.assertEqual(row["k"], reference["k"])
                        else:
                            self.assertTrue(np.isnan(row["k"]))

    def test_k_divides_only_the_residual_term(self):
        _, table = predictions("linear-shared")
        table = table.set_index("Source row")
        one, four = table.loc[0], table.loc[8]
        self.assertEqual(one["k"], 1.)
        self.assertEqual(four["k"], 4.)
        self.assertEqual(one["SE mean"], four["SE mean"])
        self.assertLess(four["Upper"] - four["Lower"], one["Upper"] - one["Lower"])
        # The drawn band stays the band of one new observation.
        result, _ = predictions("linear-shared", **{"Curve band": "Prediction"})
        band = result.tables["Curve bands"]
        expected = [row["Prediction upper"] for row in EXPECTED["linear-shared"]["curves"]]
        np.testing.assert_allclose(band["Upper"], expected, rtol=3e-6)

    def test_confidence_ignores_k(self):
        a = predictions("linear-shared", **{"Query interval": "Confidence"})[1].set_index("Source row")
        self.assertEqual(a.loc[0, "Lower"], a.loc[8, "Lower"])
        self.assertTrue(a["k"].isna().all())

    def test_point_only(self):
        _, table = predictions("linear-shared", **{"Query interval": "None"})
        self.assertTrue(table[["SE mean", "Lower", "Upper", "Level", "k"]].isna().all().all())
        self.assertEqual(set(table["Interval"]), {"None"})
        np.testing.assert_allclose(table.loc[table["Status"] == "OK", "Predicted"],
                                   [q["Predicted"] for q in EXPECTED["linear-shared"]["queries"] if q["Status"] == "OK"],
                                   rtol=3e-6)


class Outcomes(unittest.TestCase):
    def test_statuses_reasons_and_provenance(self):
        data = frame("linear-shared")
        data.index = 500 + 7 * np.arange(len(data))
        _, table = predictions("linear-shared", data)
        self.assertEqual(list(table.columns), uncertainty.PREDICTION_COLUMNS)
        self.assertEqual(table["Source row"].tolist(), data.index[:9].tolist())
        self.assertEqual(table["Status"].tolist(), [q["Status"] for q in EXPECTED["linear-shared"]["queries"]])
        bad = table[table["Status"] != "OK"]
        self.assertTrue(bad["Predicted"].isna().all())
        self.assertTrue((bad["Reason"].str.len() > 0).all())
        self.assertEqual(table.loc[table["Status"] == "Unknown group", "Group"].tolist(), ["Z"])
        self.assertIsNone(table.loc[table["Status"] == "Missing group", "Group"].iloc[0])

    def test_domain_is_per_series(self):
        # X = 4.5 is inside series B (0..6) but outside series A (0..4).
        data = frame("linear-shared")
        data.loc[4, "Query group"] = "B"
        _, table = predictions("linear-shared", data)
        self.assertEqual(table.loc[4, "Status"], "OK")
        _, table = predictions("linear-shared")
        self.assertEqual(table.loc[4, "Status"], "Outside domain")
        self.assertFalse(table.loc[4, "Extrapolated"])
        _, table = predictions("linear-shared", **{"Allow extrapolation": True})
        self.assertEqual(table.loc[4, "Status"], "Extrapolated")
        self.assertTrue(table.loc[4, "Extrapolated"])

    def test_undefined_model_keeps_other_rows(self):
        _, table = predictions("rational-domain", **{"Allow extrapolation": True})
        self.assertEqual(table["Status"].tolist(), ["Undefined model", "Extrapolated", "OK"])
        self.assertTrue(table.loc[0, "Extrapolated"])
        self.assertTrue(np.isfinite(table.loc[1:, ["Predicted", "Lower", "Upper"]].to_numpy(float)).all())

    def test_empty_label_and_null_and_unicode(self):
        _, table = predictions("linear-empty-label")
        self.assertEqual(table.loc[0, "Group"], "")
        self.assertEqual(table.loc[0, "Status"], "OK")
        self.assertEqual(table.loc[7, "Status"], "Missing group")
        data = frame("linear-shared")
        data["Group"] = data["Group"].map({"A": "Séries α, n°1", "B": "B"})
        data["Query group"] = data["Query group"].map({"A": "Séries α, n°1", "B": "B", "Z": "Z"})
        _, table = predictions("linear-shared", data)
        self.assertEqual(table.loc[0, "Group"], "Séries α, n°1")
        self.assertEqual(table.loc[0, "Status"], "OK")

    def test_numeric_groups_use_the_fit_normalisation(self):
        data = frame("linear-shared")
        data["Group"] = data["Group"].map({"A": 1, "B": 2})
        data["Query group"] = data["Query group"].map({"A": 1., "B": "2", "Z": 9})
        _, table = predictions("linear-shared", data)
        self.assertEqual(table.loc[0, "Status"], "OK")
        self.assertEqual(table.loc[1, "Status"], "OK")
        self.assertEqual(table.loc[5, "Status"], "Unknown group")

    def test_unavailable_inference_keeps_points(self):
        for name in ("linear-perfect", "all-fixed", "active-bound"):
            with self.subTest(case=name):
                _, table = predictions(name)
                rows = table[table["Status"] == "Interval unavailable"]
                self.assertGreater(len(rows), 0)
                self.assertTrue(rows["Predicted"].notna().all())
                self.assertTrue(rows[["SE mean", "Lower", "Upper"]].isna().all().all())
                self.assertTrue((rows["Reason"].str.len() > 0).all())

    def test_queries_never_feed_the_fit(self):
        plain = analyse(METHOD, frame("linear-shared"), RECIPES["linear-shared"])
        data = frame("linear-shared")
        data.loc[0, "Query X"] = 2.
        result, table = predictions("linear-shared", data)
        for sheet in ("Parameters", "Global fit", "Covariance", "Residuals", "Curve"):
            pd.testing.assert_frame_equal(plain.tables[sheet], result.tables[sheet])
        self.assertAlmostEqual(table.loc[0, "Predicted"], .98 + 1.27 * 2)
        # Query rows without any fit observation, and Query X on the fit X column itself.
        extra = pd.DataFrame({"Query X": [1., 2.], "Query group": ["B", "A"]})
        data = pd.concat([frame("linear-shared"), extra], ignore_index=True)
        result, table = predictions("linear-shared", data)
        self.assertEqual(len(table), 11)
        self.assertEqual(table["Source row"].tolist()[-2:], [9, 10])
        pd.testing.assert_frame_equal(plain.tables["Parameters"], result.tables["Parameters"])
        result, table = predictions("linear-shared", **{"Query X": "X", "Query group": "Group"})
        self.assertEqual(len(table), 9)
        np.testing.assert_allclose(table["Predicted"], result.tables["Residuals"]["Predicted"])

    def test_masked_query_x_is_missing_x_with_the_same_row(self):
        data = frame("linear-shared")
        data.loc[3, "Query X"] = np.nan
        _, table = predictions("linear-shared", data)
        self.assertEqual(table.loc[table["Source row"] == 3, "Status"].iloc[0], "Missing X")

    def test_count_alone_does_not_activate_a_row(self):
        extra = pd.DataFrame({"Query k": [3.]})
        data = pd.concat([frame("linear-shared"), extra], ignore_index=True)
        self.assertEqual(len(predictions("linear-shared", data)[1]), 9)

    def test_empty_table_keeps_the_schema(self):
        data = frame("linear-shared")
        data["Query X"] = np.nan
        data["Query group"] = None
        _, table = predictions("linear-shared", data)
        self.assertTrue(table.empty)
        self.assertEqual(list(table.columns), uncertainty.PREDICTION_COLUMNS)

    def test_sd_weights_keep_point_predictions(self):
        a = predictions("linear-weighted", **{"Query interval": "None"})[1]
        b = predictions("linear-weighted-scaled-sd", **{"Query interval": "None"})[1]
        np.testing.assert_allclose(a["Predicted"], b["Predicted"], rtol=1e-10)
        self.assertTrue(a["Lower"].isna().all())


class Validation(unittest.TestCase):
    def field(self, field, data=None, name="linear-shared", **more):
        with self.assertRaises(FieldError) as caught:
            engine.check_options(frame(name) if data is None else data, recipe(name, **more))
        self.assertEqual(caught.exception.field, field)
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, frame(name) if data is None else data, recipe(name, **more))
        self.assertEqual(caught.exception.field, field)

    def test_columns(self):
        self.field("Query X", **{"Query X": "absent"})
        self.field("Query X", **{"Query X": None})
        self.field("Query group", **{"Query group": "absent"})
        self.field("Query group", **{"Query group": "Query X"})
        self.field("Query replicate count", **{"Query replicate count": "absent"})
        self.field("Query replicate count", **{"Query replicate count": "Query X"})
        self.field("Query interval", **{"Query interval": "Simultaneous"})
        self.field("Predict responses", **{"Predict responses": "yes"})
        self.field("Allow extrapolation", **{"Allow extrapolation": 1})

    def test_query_x_values(self):
        for value in ("text", float("inf"), -np.inf, complex(1, 2), True):
            with self.subTest(value=value):
                data = frame("linear-shared")
                data["Query X"] = data["Query X"].astype(object)
                data.loc[0, "Query X"] = value
                self.field("Query X", data)
        data = frame("linear-shared")
        data["Query X"] = data["Query X"].astype(object)
        data.loc[0, "Query X"] = "1.5"
        self.assertEqual(predictions("linear-shared", data)[1].loc[0, "Status"], "OK")

    def test_replicate_counts(self):
        for value in (0, -1, 1.5, float("inf"), True, 2 ** 53 + 1, float(2 ** 54), "four"):
            with self.subTest(value=value):
                data = frame("linear-shared")
                data["Query k"] = data["Query k"].astype(object)
                data.loc[0, "Query k"] = value
                self.field("Query replicate count", data)
                # Not read with Confidence or None, nor without Predict responses.
                for interval in ("Confidence", "None"):
                    analyse(METHOD, data, recipe("linear-shared", **{"Query interval": interval}))
                analyse(METHOD, data, recipe("linear-shared", **{"Predict responses": False}))
        data = frame("linear-shared")
        data["Query k"] = data["Query k"].astype(object)
        data.loc[0, "Query k"] = 2 ** 53
        data.loc[2, "Query k"] = None
        table = predictions("linear-shared", data)[1]
        self.assertEqual(table.loc[0, "k"], float(2 ** 53))
        self.assertEqual(table.loc[2, "k"], 1.)
        # A count on an inactive row is not read.
        extra = pd.DataFrame({"Query k": [0.]})
        predictions("linear-shared", pd.concat([data, extra], ignore_index=True))

    def test_inactive_query_fields(self):
        options = copy.deepcopy(RECIPES["linear-shared"])
        options.update({"Predict responses": False, "Query X": "gone", "Query group": "gone",
                        "Query replicate count": "gone", "Query interval": "Simultaneous",
                        "Response level (%)": "inactive", "Allow extrapolation": "?"})
        result = analyse(METHOD, frame("linear-shared"), options)
        self.assertEqual(list(result.tables), ["Parameters", "Global fit", "Covariance", "Residuals", "Curve"])
        # Point predictions do not read the level.
        result, _ = predictions("linear-shared", **{"Query interval": "None", "Response level (%)": "inactive"})

    def test_weights(self):
        self.field("Query interval", name="linear-weighted")
        self.field("Curve band", name="linear-weighted", **{"Curve band": "Confidence"})

    def test_limits(self):
        source = frame("linear-shared")
        extra = pd.DataFrame({"Query X": np.ones(10_001), "Query group": "A"})
        data = pd.concat([source[["Group", "X", "Y"]], extra], ignore_index=True)
        self.field("Query X", data, **{"Query interval": "None"})
        # The propagation budget counts (band points + interval queries) times the free coordinates.
        parts = [pd.DataFrame({"X": np.arange(9.), "Y": np.arange(9.) * (1 + j) + np.sin(np.arange(9.)),
                               "Group": f"G{j}"}) for j in range(12)]
        data = pd.concat(parts + [pd.DataFrame({"Query X": np.ones(9_000), "Query group": "G0"})], ignore_index=True)
        options = {"Equation": "A+B*X+C*X^2+D*X^3", "Curve band": "Confidence", "Curve points": 2_000,
                   "Query replicate count": None,
                   "Parameters": [{"name": n, "start": 1., "shared": False, "fixed": False, "lower": None,
                                   "upper": None} for n in "ABCD"]}
        engine.check_options(data, recipe("linear-shared", **options))  # (24,000 + 9,000) × 48 cells
        options["Curve points"] = 3_000                                   # (36,000 + 9,000) × 48 cells
        with self.assertRaises(FieldError) as caught:
            engine.check_options(data, recipe("linear-shared", **options))
        self.assertEqual(caught.exception.field, "Curve points")
        engine.check_options(data, recipe("linear-shared", **options, **{"Query interval": "None"}))
        # Without a band the query rows alone are named (12 coefficients × 12 series is the largest fit).
        with self.assertRaises(FieldError) as caught:
            uncertainty.check_budget(2, 20, "None", 15_000, 144)
        self.assertEqual(caught.exception.field, "Query X")

if __name__ == "__main__":
    unittest.main()
