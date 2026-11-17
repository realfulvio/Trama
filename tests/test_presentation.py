from pathlib import Path
import tempfile
import unittest

from matplotlib.figure import Figure
import pandas as pd

from analisi.data import Dataset, load_workspace, save_project
from analisi.presentation import Layout, apply_style, compose_layout


class PresentationTests(unittest.TestCase):
    def test_layout_and_graph_style_survive_project_reload(self):
        dataset = Dataset(pd.DataFrame({"x": [1, 2], "y": [2, 3]}))
        dataset.analyses.append(("Linear regression", {"X": "x", "Y": "y"}))
        dataset.graph_styles[0] = {"title": "Dose", "grid": True}
        layout = Layout("Figure 1", 2, [("Data", 0)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.alab"
            save_project(path, {"Data": dataset}, layouts=[layout])
            tables, layouts = load_workspace(path)
        self.assertEqual(tables["Data"].graph_styles, dataset.graph_styles)
        self.assertEqual(layouts, [layout])

    def test_native_project_keeps_roc_threshold_and_v1_column_width(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.alab"
            original = {"version": 1, "tables": [
                {"title": "Wide", "columns": [f"Col {i}" for i in range(513)],
                 "kinds": ["numeric"] * 513, "rows": [[1] * 513], "formulas": []}]}
            path.write_text(json.dumps(original), encoding="utf-8")
            datasets, _ = load_workspace(path)
            self.assertEqual(datasets["Wide"].raw.shape, (1, 513))
            datasets["ROC"] = Dataset(pd.DataFrame({"Threshold": [float("inf"), 1., float("-inf")]}))
            save_project(path, datasets)
            reopened, _ = load_workspace(path)
            self.assertEqual(reopened["ROC"].raw["Threshold"].tolist(), [float("inf"), 1., float("-inf")])

    def test_layout_renders_each_graph_and_labels_panels(self):
        graphs = []
        for _ in range(2):
            figure = Figure()
            axes = figure.add_subplot()
            line, = axes.plot([1, 2, 3], [1, 4, 5])
            original_color = line.get_color()
            apply_style(figure, {"accent": "#ff00ff"})
            self.assertEqual(line.get_color(), "#ff00ff")
            apply_style(figure, {"title": "Dose", "xlabel": "Days", "grid": True, "xscale": "log"})
            self.assertEqual(axes.get_xscale(), "log")
            self.assertEqual(axes.get_title(), "Dose")
            self.assertEqual(line.get_color(), original_color)
            graphs.append(figure)
        layout = compose_layout("Figure", 2, graphs)
        self.assertEqual(len(layout.axes), 2)
        self.assertEqual([ax.get_title(loc="left") for ax in layout.axes], ["A", "B"])
        self.assertEqual([len(ax.images) for ax in layout.axes], [1, 1])
