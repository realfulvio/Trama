"""Tests for Empirical cumulative distribution (ECDF): contract, stats, graph artists, ALAB and exports."""
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi import ecdf_graph as ecdf
from analisi.category_order import WORKSHEET_ORDERS
from analisi.data import Dataset, load_workspace, save_project
from analisi.figure_export import export_figure
from analisi.graph_legend import collect_legend_entries, is_valid_entry_key, typed_group_token
from analisi.linked_axes import LINKED_AXES, supported_dimensions
from analisi.presentation import apply_style, graph_series, validate_graph_style
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse


FIXTURE = Path(__file__).resolve().parent / "data" / "ecdf_graph" / "synthetic.csv"


def _oracle(values):
    clean = [0.0 if v == 0 else float(v) for v in values]
    n = len(clean)
    return [
        (x, clean.count(x), sum(v <= x for v in clean), Fraction(sum(v <= x for v in clean), n))
        for x in sorted(set(clean))
    ]


class EcdfContractTests(unittest.TestCase):
    def test_ecdf_points_matches_exact_oracle(self):
        cases = (
            [-1, 0, 0, 3],
            [4, 4, 4],
            [9, 1, 4, 3, 1, 2],
            [0.0, -0.0],
            [-0.0, 0.0, -0.0],
            [-10.5, -10.5, -2.25, 0.0, 7.5],
            pd.Series([3.0, 1.0, 1.0, 2.0]),
            np.array([5.0]),
        )
        for values in cases:
            frame = ecdf.ecdf_points(values)
            self.assertEqual(list(frame.columns), ["X", "Count", "Cumulative count", "Probability"])
            rows = list(frame.itertuples(index=False, name=None))
            expected = _oracle(list(values))
            self.assertEqual(len(rows), len(expected))
            for actual, want in zip(rows, expected, strict=True):
                self.assertEqual(actual[:3], want[:3])
                self.assertAlmostEqual(actual[3], float(want[3]), places=14)
            self.assertEqual(rows[-1][3], 1.0)
            self.assertTrue((frame["X"].to_numpy()[:-1] < frame["X"].to_numpy()[1:]).all())

    def test_ecdf_points_validates_inputs(self):
        for bad in ([], None, "123", b"123", {"a": 1}, [[1, 2]], [1.0, np.nan], [1.0, np.inf],
                    [1.0, -np.inf], [True, False], [1, True], [1 + 2j, 3 + 0j], ["a", "b"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ecdf.ecdf_points(bad)


class EcdfEngineAndGraphTests(unittest.TestCase):
    def test_workbench_registration_and_graph_membership(self):
        self.assertIn(ecdf.METHOD, METHODS)
        self.assertIn(ecdf.METHOD, GROUPS["Graphing"])
        self.assertIn(ecdf.METHOD, GRAPH_METHODS)

    def test_two_series_ties_negative_excluded_and_y_unit_csv_equality(self):
        raw = pd.DataFrame({
            "Series A": [-2.0, 0.0, 0.0, 3.0, 99.0],
            "Series B": [0.0, 1.0, 1.0, 4.0, np.nan],
            "Unused text": ["note", "bad", "text", "ignored", "here"],
        })
        ds = Dataset(raw, excluded={(4, 0)})  # exclude 99.0 from Series A
        frame = ds.frame(mask_excluded=True)

        prop = analyse(ecdf.METHOD, frame, {
            ecdf.INPUT: ecdf.SEPARATE,
            ecdf.VARIABLES: ["Series B", "Series A"],
            ecdf.Y_AXIS: ecdf.PROPORTION,
        })
        pct = analyse(ecdf.METHOD, frame, {
            ecdf.INPUT: ecdf.SEPARATE,
            ecdf.VARIABLES: ["Series B", "Series A"],
            ecdf.Y_AXIS: ecdf.PERCENT,
        })

        # Selection order is preserved (Series B before Series A).
        summary = prop.tables[ecdf.SUMMARY_SHEET]
        self.assertEqual(summary["Group"].tolist(), ["Series B", "Series A"])
        self.assertEqual(summary["N"].tolist(), [4, 4])
        self.assertEqual(summary["Excluded"].tolist(), [1, 1])
        self.assertEqual(summary["Distinct values"].tolist(), [3, 3])

        # Exported ECDF points CSV is byte-for-byte identical across Proportion and Percent.
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = Path(tmp) / "prop.csv", Path(tmp) / "pct.csv"
            prop.tables[ecdf.POINTS_SHEET].to_csv(p1, index=False)
            pct.tables[ecdf.POINTS_SHEET].to_csv(p2, index=False)
            self.assertEqual(p1.read_bytes(), p2.read_bytes())

        pts = prop.tables[ecdf.POINTS_SHEET]
        self.assertEqual(list(pts.columns), list(ecdf.LONG_POINTS_COLUMNS))
        self.assertTrue(((pts["Probability"] > 0.0) & (pts["Probability"] <= 1.0)).all())

        # Check graph artists, steps-post drawstyle, zero slope between jumps, 0 and 1 borders without extra rows.
        for result, scale, expected_ylabel in (
            (prop, 1.0, "Cumulative probability"),
            (pct, 100.0, "Cumulative probability (%)"),
        ):
            axes = result.figure.axes[0]
            self.assertEqual(axes.get_ylabel(), expected_ylabel)
            self.assertEqual(len(axes.lines), 2)
            left, right = axes.get_xlim()
            for line, group_name in zip(axes.lines, ["Series B", "Series A"], strict=True):
                self.assertEqual(line.get_drawstyle(), "steps-post")
                self.assertEqual(line.get_label(), group_name)
                xd = np.asarray(line.get_xdata(), dtype=float)
                yd = np.asarray(line.get_ydata(), dtype=float)
                group_pts = pts[pts["Group"] == group_name]
                # Table has only distinct observed values; plotted trace adds left (0) and right (1) borders.
                self.assertEqual(len(xd), len(group_pts) + 2)
                self.assertAlmostEqual(xd[0], left)
                self.assertAlmostEqual(xd[-1], right)
                self.assertEqual(yd[0], 0.0)
                self.assertAlmostEqual(yd[-1], scale)
                np.testing.assert_allclose(xd[1:-1], group_pts["X"].to_numpy())
                np.testing.assert_allclose(yd[1:-1], group_pts["Probability"].to_numpy() * scale)
                # Verify rendered step path has only horizontal (dy == 0) and vertical (dx == 0) segments,
                # with horizontal plateaus extending strictly to the right of each jump.
                path = line.get_path()
                verts = path.vertices
                dx = np.diff(verts[:, 0])
                dy = np.diff(verts[:, 1])
                for seg_dx, seg_dy in zip(dx, dy, strict=True):
                    self.assertTrue(abs(seg_dx) < 1e-12 or abs(seg_dy) < 1e-12, (seg_dx, seg_dy))
                    self.assertGreaterEqual(seg_dx, -1e-12)
                    self.assertGreaterEqual(seg_dy, -1e-12)

    def test_constant_series_is_single_step_from_zero_to_one(self):
        frame = pd.DataFrame({"Const": [4.0, 4.0, 4.0], "Other": [1.0, 2.0, 5.0]})
        # Constant alone
        alone = analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: ["Const"]})
        pts = alone.tables[ecdf.POINTS_SHEET]
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts.iloc[0]["X"], 4.0)
        self.assertEqual(pts.iloc[0]["Count"], 3)
        self.assertEqual(pts.iloc[0]["Cumulative count"], 3)
        self.assertEqual(pts.iloc[0]["Probability"], 1.0)
        self.assertIn("Constant", alone.tables[ecdf.SUMMARY_SHEET].iloc[0]["Note"])
        axes = alone.figure.axes[0]
        left, right = axes.get_xlim()
        self.assertLess(left, 4.0)
        self.assertGreater(right, 4.0)
        line = axes.lines[0]
        np.testing.assert_allclose(line.get_xdata(), [left, 4.0, right])
        np.testing.assert_allclose(line.get_ydata(), [0.0, 1.0, 1.0])

        # Constant alongside another series
        both = analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: ["Other", "Const"]})
        self.assertEqual(both.tables[ecdf.SUMMARY_SHEET]["Distinct values"].tolist(), [3, 1])

    def test_empty_series_or_empty_group_raises_explicit_field_error(self):
        frame = pd.read_csv(FIXTURE)
        # Empty selected column in Separate columns mode
        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: ["Series A", "Empty"]})
        self.assertEqual(caught.exception.field, ecdf.VARIABLES)
        self.assertIn("Empty", str(caught.exception))

        # Empty group in Single response + Group mode
        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, frame, {
                ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "Long X", ecdf.GROUP: "Long Group",
            })
        self.assertEqual(caught.exception.field, ecdf.GROUP)
        self.assertIn("Empty", str(caught.exception))

        # Completely empty response column without group
        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "Empty"})
        self.assertEqual(caught.exception.field, ecdf.RESPONSE)

    def test_single_response_grouped_and_ungrouped_with_typed_tokens_and_order(self):
        frame = pd.DataFrame({
            "Y": [10.0, 20.0, np.nan, 5.0, 5.0, 30.0],
            "G": pd.Series([1, 1, 1, "1", "1", None], dtype=object),
            "Irrelevant": ["bad", "text", np.inf, None, "x", "y"],
        })
        result = analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "Y", ecdf.GROUP: "G"})
        summary = result.tables[ecdf.SUMMARY_SHEET]
        self.assertEqual(len(summary), 2)
        self.assertEqual(summary["N"].tolist(), [2, 2])
        self.assertEqual(summary["Excluded"].tolist(), [1, 0])
        self.assertEqual(result.tables["Settings"].loc["Rows omitted (missing group)", "Value"], 1)

        # Worksheet category order is respected
        ordered = pd.DataFrame({"Y": [1.0, 2.0, 3.0, 4.0], "G": ["First", "First", "Second", "Second"]})
        ordered.attrs[WORKSHEET_ORDERS] = {"G": [typed_group_token("Second"), typed_group_token("First")]}
        res_ordered = analyse(ecdf.METHOD, ordered, {ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "Y", ecdf.GROUP: "G"})
        self.assertEqual(res_ordered.tables[ecdf.SUMMARY_SHEET]["Group"].tolist(), ["Second", "First"])

        # Ungrouped Single response
        single = analyse(ecdf.METHOD, ordered, {ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "Y"})
        self.assertEqual(single.tables[ecdf.SUMMARY_SHEET]["Group"].tolist(), ["All"])
        self.assertEqual(single.figure.axes[0].get_xlabel(), "Y")

    def test_curve_limits_1_to_12(self):
        cols12 = {f"C{i}": [float(i), float(i + 1)] for i in range(1, 13)}
        res12 = analyse(ecdf.METHOD, pd.DataFrame(cols12), {
            ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: list(cols12),
        })
        self.assertEqual(len(res12.figure.axes[0].lines), 12)

        cols13 = {**cols12, "C13": [13.0, 14.0]}
        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, pd.DataFrame(cols13), {
                ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: list(cols13),
            })
        self.assertEqual(caught.exception.field, ecdf.VARIABLES)

        long13 = pd.DataFrame({"Y": np.arange(13.0), "G": [f"G{i}" for i in range(13)]})
        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, long13, {ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "Y", ecdf.GROUP: "G"})
        self.assertEqual(caught.exception.field, ecdf.GROUP)

    def test_non_finite_values_rejected_like_adjacent_graphs(self):
        frame = pd.DataFrame({"A": [1.0, np.inf, 2.0], "B": [1.0, 2.0, 3.0]})
        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: ["A", "B"]})
        self.assertEqual(caught.exception.field, ecdf.VARIABLES)

        with self.assertRaises(FieldError) as caught:
            analyse(ecdf.METHOD, frame, {ecdf.INPUT: ecdf.SINGLE, ecdf.RESPONSE: "A"})
        self.assertEqual(caught.exception.field, ecdf.RESPONSE)

    def test_format_graph_legend_linked_axes_and_vector_exports(self):
        frame = pd.DataFrame({"A": [-1.0, 0.0, 0.0, 3.0], "B": [0.5, 1.5, 2.5, 4.0]})
        result = analyse(ecdf.METHOD, frame, {
            ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: ["A", "B"], ecdf.Y_AXIS: ecdf.PROPORTION,
        })
        axes = result.figure.axes[0]
        self.assertEqual(supported_dimensions(axes), ("x", "y"))
        series = graph_series(axes)
        self.assertEqual(len(series), 2)
        entries = collect_legend_entries(result.figure)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(is_valid_entry_key(entry.key) for entry in entries))

        style = {
            "title": "Custom ECDF",
            "xlabel": "Measurement",
            "grid": True,
            "legend": "lower right",
            "series": {series[0].key: {"color": "#cc3311", "width": 2.5}},
            LINKED_AXES: {"x": {"multiplier": 2.0, "offset": 0.0, "label": "2X"}},
        }
        validate_graph_style(axes, style)
        apply_style(result.figure, style)
        self.assertEqual(axes.get_title(), "Custom ECDF")
        self.assertEqual(axes.lines[0].get_color(), "#cc3311")

        # Switching Y axis unit clears stale Y settings while keeping title & series colors
        cleaned = ecdf.style_after_parameter_change(
            {**style, "ylabel": "Cumulative probability", "axis": {"y": {"min": 0.0, "max": 1.0}}},
            {ecdf.Y_AXIS: ecdf.PROPORTION},
            {ecdf.Y_AXIS: ecdf.PERCENT},
        )
        self.assertNotIn("ylabel", cleaned)
        self.assertNotIn("axis", cleaned)
        self.assertEqual(cleaned["title"], "Custom ECDF")

        with tempfile.TemporaryDirectory() as tmp:
            for fmt, suffix in (("png", ".png"), ("svg", ".svg"), ("pdf", ".pdf")):
                target = Path(tmp) / f"ecdf{suffix}"
                settings = {"format": fmt, "dpi": 150} if fmt == "png" else {"format": fmt}
                export_figure(result.figure, target, settings)
                self.assertTrue(target.exists() and target.stat().st_size > 200, fmt)
            svg_text = (Path(tmp) / "ecdf.svg").read_text(encoding="utf-8")
            self.assertIn("<svg", svg_text)
            self.assertIn("Custom ECDF", svg_text)

    def test_alab_roundtrip_edit_and_recalculate(self):
        raw = pd.DataFrame({"A": [-1.0, 0.0, 0.0, 3.0], "B": [0.0, 2.0, 2.0, 5.0]})
        recipe = {ecdf.INPUT: ecdf.SEPARATE, ecdf.VARIABLES: ["B", "A"], ecdf.Y_AXIS: ecdf.PERCENT}
        ds = Dataset(raw, analyses=[(ecdf.METHOD, recipe)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ecdf.alab"
            save_project(path, {"Data": ds})
            loaded, _ = load_workspace(path)
            saved_method, saved_options = loaded["Data"].analyses[0]
            self.assertEqual(saved_method, ecdf.METHOD)
            self.assertEqual(saved_options, recipe)

            before = analyse(saved_method, loaded["Data"].frame(mask_excluded=True), saved_options)
            loaded["Data"].raw.iat[0, 0] = -5.0  # change A[0] from -1.0 to -5.0
            after = analyse(saved_method, loaded["Data"].frame(mask_excluded=True), saved_options)

            a_before = before.tables[ecdf.POINTS_SHEET]
            a_after = after.tables[ecdf.POINTS_SHEET]
            self.assertEqual(a_before[a_before["Group"] == "A"]["X"].iloc[0], -1.0)
            self.assertEqual(a_after[a_after["Group"] == "A"]["X"].iloc[0], -5.0)
            self.assertEqual(after.figure.axes[0].lines[1].get_xdata()[1], -5.0)


if __name__ == "__main__":
    unittest.main()
