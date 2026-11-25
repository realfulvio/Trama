"""Imported model comparison binds archive rows to the original worksheet."""
from copy import deepcopy
from math import log
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import advanced
from analisi.kmeans_archive import ARCHIVE, restore
from analisi.kmeans_options import ALGORITHM, HARTIGAN, INITIALIZATION, KMEANS_PLUS_PLUS, SELECTION
from analisi.kmeans_reports import ASSIGNMENTS, ASSIGNMENTS_TABLE
from analisi.workbench import analyse


def _fit_record(values, groups, offset):
    clusters = []
    total = 0.0
    for rows in groups:
        mean = sum(values[row] for row in rows) / len(rows)
        points = [{"id": row, "distance": abs(values[row] - mean)} for row in rows]
        total += sum(point["distance"] ** 2 for point in points)
        clusters.append({"points": points})
    observed = log(total)
    return {"status": "VALID", "wcss": total, "clusters": clusters,
            "gap": {"statistic": offset, "sd": 0.125, "logWObserved": observed,
                    "logWExpected": observed + offset}}


class KMeansArchiveTests(unittest.TestCase):
    def setUp(self):
        values = [0., 2., 7., 10.]
        self.frame = pd.DataFrame({"Value": values, "Notes": ["a", "b", "c", "d"]})
        self.options = {"Variables": ["Value"], "Minimum k": 1, "Maximum k": 2, "Seed": 77,
                        ALGORITHM: HARTIGAN, "Criterion": "Consensus (17 indices)", "Gap simulations": 5,
                        ASSIGNMENTS: True}
        self.results = {"content": {"status": {"error": "VALID"},
                                    "dataSummary": {"variablesCount": 1, "rowsTotal": 4, "rowsSkipped": 0,
                                                    "rowsAnalyzed": 4},
                                    "models": {"1": _fit_record(values, [[0, 1, 2, 3]], 0.25),
                                               "2": _fit_record(values, [[2, 3], [0, 1]], 1.25)}}}

    def options_with_archive(self):
        saved = restore(self.frame, self.options, self.results)
        self.assertIsNotNone(saved)
        return {**self.options, ARCHIVE: saved}

    def test_reports_use_saved_memberships_and_gap_without_refitting(self):
        options = self.options_with_archive()
        with patch.object(advanced, "_scan_fit", side_effect=AssertionError("Unexpected live fit")), \
                patch.object(advanced, "_gap_scores", side_effect=AssertionError("Unexpected reference simulation")):
            unchanged = self.frame.assign(Notes="Changed descriptive column")
            result = analyse(SELECTION, unchanged, options)
        table = result.tables[ASSIGNMENTS_TABLE]
        np.testing.assert_array_equal(table["Cluster (k=2)"], [2, 2, 1, 1])
        self.assertEqual(table["Notes"].tolist(), ["Changed descriptive column"] * 4)
        self.assertEqual(result.tables["Selection"].loc["Result source", "Value"],
                         "Saved partitions and Gap statistics")
        self.assertNotIn("Gap simulations", result.tables["Selection"].index)
        self.assertEqual(result.tables["Cluster metrics"].loc[2, "Gap"], 1.25)

    def test_iteration_report_reuses_recorded_counts_when_available(self):
        models = self.results["content"]["models"]
        models["1"]["iterationCount"] = 0
        models["2"]["iterationCount"] = 3
        options = {**self.options_with_archive(), "Report K-means fit diagnostics": True}
        with patch.object(advanced, "_scan_fit", side_effect=AssertionError("Unexpected live fit")):
            table = analyse(SELECTION, self.frame, options).tables["K-means fit diagnostics"]
        self.assertEqual(table["Iterations"].tolist(), [0, 3])
        self.assertEqual(table["Fit source"].tolist(), ["Saved fit"] * 2)
        self.assertEqual(table["Stop reason"].tolist(), ["Not recorded"] * 2)
        options[ARCHIVE]["models"][0].pop("iterations")
        options[ARCHIVE]["models"][1]["iterations"] = True
        result = analyse(SELECTION, self.frame, options)
        self.assertTrue(result.tables["K-means fit diagnostics"]["Iterations"].isna().all())
        self.assertEqual(result.tables["Selection"].at["Result source", "Value"],
                         "Saved partitions and Gap statistics")

    def test_edit_exclusion_or_configuration_change_recalculates(self):
        options = self.options_with_archive()
        edited = self.frame.copy()
        edited.loc[0, "Value"] = 1.
        excluded = self.frame.copy()
        excluded.loc[0, "Value"] = np.nan
        cases = ((edited, options), (excluded, options), (self.frame.iloc[::-1], options),
                 (self.frame, {**options, INITIALIZATION: KMEANS_PLUS_PLUS}))
        for frame, settings in cases:
            with self.subTest(rows=frame.index.tolist(), settings=settings.get(INITIALIZATION)):
                result = analyse(SELECTION, frame, settings)
                self.assertEqual(result.tables["Selection"].loc["Result source", "Value"],
                                 "Recalculated in Trama")

    def test_identical_measurements_in_distinct_clusters_have_ambiguous_identity(self):
        frame = self.frame.copy()
        frame.loc[1, "Value"] = 7.
        values = frame["Value"].tolist()
        data = self.results["content"]["models"]
        data["1"] = _fit_record(values, [[0, 1, 2, 3]], 0.25)
        data["2"] = _fit_record(values, [[0, 1], [2, 3]], 1.25)
        self.assertIsNone(restore(frame, self.options, self.results))
        data["2"] = _fit_record(values, [[0], [1, 2, 3]], 1.25)
        self.assertIsNotNone(restore(frame, self.options, self.results))

    def test_inconsistent_membership_or_wss_is_rejected(self):
        inconsistent = deepcopy(self.results)
        inconsistent["content"]["models"]["2"]["clusters"][0]["points"][0]["id"] = 0
        self.assertIsNone(restore(self.frame, self.options, inconsistent))
        inconsistent = deepcopy(self.results)
        inconsistent["content"]["models"]["2"]["wcss"] *= 1.01
        self.assertIsNone(restore(self.frame, self.options, inconsistent))
        options = self.options_with_archive()
        options[ARCHIVE]["models"][1]["groups"] = [1, 1, 1, 2]
        result = analyse(SELECTION, self.frame, options)
        self.assertEqual(result.tables["Selection"].loc["Result source", "Value"], "Recalculated in Trama")
