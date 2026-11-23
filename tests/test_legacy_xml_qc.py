import unittest

from matplotlib.colors import to_hex
import numpy as np
import pandas as pd

from analisi.legacy_restore import SAVED_XY
from analisi.legacy_xml_qc import QC_POINTS, QC_REFERENCE, XML_QC
from analisi.workbench import analyse


class ImportedQcGraphTests(unittest.TestCase):
    def test_graph_uses_recalculated_summary_and_preserves_worksheet_row_colors(self):
        source = pd.DataFrame({"Ref": [10., 11., np.nan, 13., 16.], "Other": [18., 19., 20., 21., 22.]})
        options = {"Variables": ["Ref", "Other"], QC_REFERENCE: "Ref"}
        style = {
            "series": [{"column": "Ref", "x": .25, "size": 5, "color": "#000000", "points": [[3, "#ff0000"]]},
                       {"column": "Other", "x": .75, "size": 5, "color": "#000000", "points": []}],
            "limits": [0., 40.], "ticks": [0., 20., 40.], "title": "", "ylabel": "Response", "aspect": .7,
            "band": {"alpha": .2, "center": 0., "color": "#0080ff"},
        }
        source_bounds = []
        for edit in (0., 20.):
            candidate = source.copy()
            candidate.at[0, "Ref"] += edit
            result = analyse("Descriptive statistics", candidate, options)
            summary = result.tables["Summary"].loc["Ref"]
            values = candidate["Ref"].dropna().to_numpy()
            np.testing.assert_allclose([summary["Q1"], summary["Q3"]], np.quantile(values, [.25, .75], method="weibull"))
            graph = analyse(SAVED_XY, result.tables[QC_POINTS], {XML_QC: style})
            axes, = graph.figure.axes
            span, = axes.patches
            self.assertEqual(span.get_gid(), "linked-control-band")
            bounds = [values.mean() - values.std(ddof=1), values.mean() + values.std(ddof=1)]
            np.testing.assert_allclose([span.get_y(), span.get_y() + span.get_height()], bounds)
            observations = graph.tables["Saved XY coordinates"].query("Series == 'Ref'")
            self.assertEqual(observations["Source row"].tolist(), [1, 2, 4, 5])
            self.assertEqual([to_hex(color) for color in axes.collections[0].get_facecolors()],
                             ["#000000", "#000000", "#ff0000", "#000000"])
            source_bounds.append(bounds)
        self.assertNotEqual(*source_bounds)

    def test_missing_reference_suppresses_the_band_while_preserving_points(self):
        frame = pd.DataFrame({"B": [10., 20., 30.]})
        options = {"Variables": ["B"], QC_REFERENCE: "A"}
        result = analyse("Descriptive statistics", frame, options)
        graph = analyse(SAVED_XY, result.tables[QC_POINTS], {XML_QC: {
            "series": [{"column": "B", "x": .5, "size": 5, "color": "#000000", "points": []}],
            "limits": [0., 40.], "ticks": [0., 20., 40.], "title": "", "ylabel": "", "aspect": .7,
            "band": {"alpha": .2, "center": 0., "color": "#0080ff"},
        }})
        self.assertEqual(len(graph.figure.axes[0].patches), 0)
        self.assertEqual(len(graph.tables["Saved XY coordinates"]), 3)
