import unittest

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg

from analisi.workbench import analyse, classic_roles


class MultipleVariableClassicTests(unittest.TestCase):
    def test_nonlinear_curves_follow_response_and_group_roles(self):
        x = np.tile(np.linspace(1, 20, 24), 4)
        group = np.repeat(np.arange(4), 24)
        data = pd.DataFrame({"Dose": x, "Treatment": np.where(group < 2, "A", "B"),
                             "Stage": group % 2, "Y1": 2 + (6 + group) * np.exp(-.18 * x),
                             "Y2": 4 + (7 + group) * np.exp(-.31 * x)})
        data.loc[1, "Y2"] = np.nan
        data.loc[2, "Treatment"] = None
        result = analyse("Nonlinear regression", data, {
            "X": "Dose", "Y columns": ["Y1", "Y2"], "Grouping variables": ["Treatment", "Stage"],
            "Model": "One-phase decay",
        })
        self.assertEqual([axes.get_title() for axes in result.figure.axes], ["Y1", "Y2"])
        parameters = result.tables["Parameters"].set_index(["Parameter", "Response variable"])
        np.testing.assert_allclose(parameters.loc[("Rate", "Y1"), "Estimate"], [.18] * 4, rtol=1e-6)
        np.testing.assert_allclose(parameters.loc[("Rate", "Y2"), "Estimate"], [.31] * 4, rtol=1e-6)
        n = result.tables["Fit"].set_index(["Metric", "Response variable"])
        self.assertEqual(n.loc[("N", "Y1"), "Value"].tolist(), [23, 24, 24, 24])
        self.assertEqual(n.loc[("N", "Y2"), "Value"].tolist(), [22, 24, 24, 24])

    def test_survival_comparisons_use_complete_cases_per_response(self):
        time = np.tile(np.arange(1, 11), 4) + np.repeat([0, 1, 2, 3], 10)
        data = pd.DataFrame({"Time": time, "Treatment": np.repeat(["A", "B"], 20),
                             "Stage": np.repeat(["Early", "Late"] * 2, 10),
                             "Death": np.tile([1, 1, 0, 1, 0], 8),
                             "Relapse": np.tile([1, 1, 1, 0, 1], 8).astype(float)})
        data.loc[0, "Relapse"] = np.nan
        data.loc[10, "Stage"] = None
        missing = pd.DataFrame({"Time": 1, "Treatment": [f"unused{i}" for i in range(33)], "Stage": "Late",
                                "Death": np.nan, "Relapse": np.nan})
        result = analyse("Kaplan–Meier survival", pd.concat([data, missing], ignore_index=True), {
            "Time": "Time", "Event columns": ["Death", "Relapse"], "Grouping variables": ["Treatment", "Stage"],
            "Pairwise correction": "Holm", "Show risk table below graph": True,
        })
        summary = result.tables["Survival summary"].set_index("Response variable")
        self.assertEqual(summary.loc["Death", "N"].tolist(), [10, 9, 10, 10])
        self.assertEqual(summary.loc["Relapse", "N"].tolist(), [9, 9, 10, 10])
        self.assertEqual(result.tables["Pairwise log-rank"].groupby("Response variable").size().tolist(), [6, 6])
        self.assertEqual(list(result.tables["Number at risk"].columns), ["Response variable", "Group", "Time", "At risk"])
        canvas = FigureCanvasAgg(result.figure)
        canvas.draw()
        risk_tables = [table for axes in result.figure.axes for table in axes.tables]
        self.assertEqual(len(risk_tables), 2)
        for table in risk_tables:
            bounds = table.get_window_extent(canvas.get_renderer())
            self.assertGreaterEqual(bounds.y0, 0)
            self.assertLessEqual(bounds.y1, result.figure.bbox.y1)
        one = data.assign(Group=data["Treatment"].str.cat(data["Stage"], sep="/"))
        reference = analyse("Kaplan–Meier survival", one, {"Time": "Time", "Event": "Relapse", "Group": "Group"})
        tests = result.tables["Log-rank test"].set_index(["Response variable", "Metric"])
        self.assertAlmostEqual(tests.loc[("Relapse", "p"), "Value"],
                               reference.tables["Log-rank test"].loc["p", "Value"])

    def test_legacy_options_load_and_explicit_duplicates_are_rejected(self):
        self.assertEqual(classic_roles("Nonlinear regression", {"Y": "Old", "Group": "Arm"}),
                         {"Y columns": ["Old"], "Grouping variables": ["Arm"]})
        with self.assertRaisesRegex(ValueError, "distinct"):
            analyse("Kaplan–Meier survival", pd.DataFrame({"Time": [1, 2], "Event": [0, 1]}),
                    {"Time": "Time", "Event columns": ["Event", "Event"]})
