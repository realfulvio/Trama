import tempfile
import unittest
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
import pandas as pd

from analisi.data import Dataset, load_workspace, save_project
from analisi.presentation import apply_style, graph_series, validated_style


class GraphFormatTests(unittest.TestCase):
    def graph(self):
        figure = Figure(layout="constrained")
        axes = figure.add_subplot()
        line, = axes.plot([1, 2, 3], [3, 6, 8], label="Trend")
        dots = axes.scatter([1, 3], [3, 8], label="Sample")
        axes.legend(loc="lower right")
        return figure, axes, line, dots

    def test_advanced_style_persists_renders_and_resets(self):
        style = {
            "axis": {"x": {"min": 0.5, "max": 3.5, "step": 1, "start": 0.5,
                           "minor": 4, "decimals": 1}},
            "grid": True, "grid_minor": True, "frame": "box",
            "title": "Formatted", "title_size": 18, "label_size": 13, "tick_size": 9,
            "font_family": "serif", "legend": "upper left", "legend_size": 12,
            "series": {"line:1:Trend": {"color": "#b04026", "line_style": "dashed", "width": 2.5},
                       "scatter:1:Sample": {"color": "#066677", "marker": "s", "marker_size": 8}},
            "reference_lines": [{"axis": "y", "value": 5.5, "label": "Target"}],
        }
        dataset = Dataset(pd.DataFrame({"x": [1, 2], "y": [2, 3]}))
        dataset.analyses.append(("Linear regression", {"X": "x", "Y": "y"}))
        dataset.graph_styles[0] = style
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "formatted.alab"
            save_project(path, {"Data": dataset})
            reopened, _ = load_workspace(path)
            self.assertEqual(reopened["Data"].graph_styles[0], style)

        figure, axes, line, dots = self.graph()
        original_xlim = axes.get_xlim()
        original_marker = dots.get_paths()[0]
        original_legend = axes.get_legend()
        original_color = line.get_color()
        apply_style(figure, reopened["Data"].graph_styles[0])
        FigureCanvasAgg(figure).draw()
        self.assertEqual(tuple(axes.get_xlim()), (0.5, 3.5))
        self.assertEqual(list(axes.get_xticks()), [0.5, 1.5, 2.5, 3.5])
        self.assertIn(0.75, axes.get_xticks(minor=True))
        self.assertEqual([label.get_text() for label in axes.get_xticklabels()], ["0.5", "1.5", "2.5", "3.5"])
        self.assertEqual(axes.get_xticklabels()[0].get_fontsize(), 9)
        self.assertEqual(axes.title.get_fontsize(), 18)
        self.assertEqual(axes.title.get_fontfamily(), ["serif"])
        self.assertEqual(axes.get_legend().get_texts()[0].get_fontsize(), 12)
        self.assertEqual(axes.get_legend().get_lines()[0].get_color(), "#b04026")
        self.assertEqual(line.get_linestyle(), "--")
        self.assertEqual(line.get_linewidth(), 2.5)
        self.assertEqual(tuple(dots.get_facecolors()[0]), to_rgba("#066677"))
        self.assertEqual(dots.get_sizes().tolist(), [64])
        self.assertIsNot(dots.get_paths()[0], original_marker)
        self.assertEqual([label.get_text() for label in axes.texts], ["Target"])

        apply_style(figure, {})
        FigureCanvasAgg(figure).draw()
        self.assertEqual(axes.get_title(), "")
        self.assertEqual(axes.get_xlim(), original_xlim)
        self.assertEqual(line.get_color(), original_color)
        self.assertEqual(line.get_linestyle(), "-")
        self.assertIs(dots.get_paths()[0], original_marker)
        self.assertIs(axes.get_legend(), original_legend)
        self.assertEqual(list(axes.texts), [])

    def test_invalid_format_preserves_already_applied_style(self):
        figure, axes, line, _ = self.graph()
        apply_style(figure, {"title": "Kept", "accent": "red"})
        bad_styles = (
            {"axis": {"x": {"min": 3, "max": 2}}},
            {"xscale": "linear", "axis": {"x": {"min": 1, "max": 1 + 2e-16}}},
            {"axis": {"x": {"min": 0, "max": 20, "step": .0001}}},
            {"xscale": "log", "axis": {"x": {"min": 0, "max": 20}}},
            {"xscale": "log", "axis": {"x": {"step": 2}}},
            {"title_size": float("nan")},
            {"xlabel": r"$\unrecognizedcommand$"},
            {"series": {"line:1:Trend": {"marker": "bogus"}}},
            {"reference_lines": [{"axis": "y", "value": float("inf")}]},
        )
        for style in bad_styles:
            with self.subTest(style=style), self.assertRaises(ValueError):
                apply_style(figure, {"title": "Invalid", **style})
            self.assertEqual(axes.get_title(), "Kept")
            self.assertEqual(line.get_color(), "red")

    def test_categorical_labels_remain_intact_and_numeric_options_are_rejected(self):
        figure = Figure()
        axes = figure.add_subplot()
        axes.bar([1, 2], [3, 5], label="Bars")
        axes.set_xticks([1, 2], ["Control", "Treatment"])
        apply_style(figure, {"tick_size": 11, "series": {"bar:1:Bars": {"color": "teal"}}})
        self.assertEqual([label.get_text() for label in axes.get_xticklabels()], ["Control", "Treatment"])
        self.assertEqual(axes.patches[0].get_facecolor(), to_rgba("teal"))
        with self.assertRaisesRegex(ValueError, "numeric"):
            apply_style(figure, {"axis": {"x": {"step": 1}}})
        self.assertEqual(axes.patches[0].get_facecolor(), to_rgba("teal"))

    def test_named_series_stays_with_its_label_after_reordering(self):
        figure = Figure()
        axes = figure.add_subplot()
        line_b, = axes.plot([1, 2], [2, 3], label="B")
        line_a, = axes.plot([1, 2], [3, 4], label="A")
        apply_style(figure, {"legend": "hidden", "series": {"line:1:A": {"color": "red"}}})
        self.assertNotEqual(line_b.get_color(), "red")
        self.assertEqual(line_a.get_color(), "red")
        self.assertIsNone(axes.get_legend())

    def test_unsupported_artist_property_rejected_by_project_validator(self):
        with self.assertRaises(ValueError):
            validated_style({"series": {"scatter:1:Data": {"line_style": "dashed"}}})

    def test_zoom_beyond_fixed_tick_capacity_uses_safe_locator(self):
        figure, axes, _, _ = self.graph()
        style = {"axis": {"x": {"min": 1, "max": 3, "step": .1}}}
        apply_style(figure, style)
        axes.set_xlim(-1e5, 1e5)
        self.assertLess(len(axes.get_xticks()), 20)
        apply_style(figure, {**style, "title": "During zoom"})
        self.assertEqual(axes.get_xlim(), (-1e5, 1e5))

    def test_references_keep_data_limits_and_can_be_replaced(self):
        figure, axes, _, _ = self.graph()
        original_data = axes.dataLim.bounds
        apply_style(figure, {"reference_lines": [{"axis": "x", "value": 20, "label": "Far"}]})
        self.assertEqual(axes.dataLim.bounds, original_data)
        apply_style(figure, {"reference_lines": [{"axis": "y", "value": 5, "label": "Midpoint"}]})
        self.assertEqual([label.get_text() for label in axes.texts], ["Midpoint"])
        self.assertEqual(len(axes.lines), 2)

    def test_errorbar_series_styles_points_caps_whiskers_and_one_legend_entry(self):
        figure = Figure()
        axes = figure.add_subplot()
        group = axes.errorbar([1, 2], [2, 4], xerr=.1, yerr=.4,
                              capsize=4, label="Treated", fmt="o", ecolor="gray")
        center, caps, whiskers = group.lines
        original_color = center.get_color()
        axes.legend()
        other, = axes.plot([1, 2], [2, 5])
        self.assertEqual({series.key for series in graph_series(axes)},
                         {"errorbar:1:Treated", f"line:{len(caps) + 2}:"})
        style = {"accent": "blue",
                 "series": {"errorbar:1:Treated": {"color": "red", "marker": "s", "label": "Revised"}}}
        apply_style(figure, style)
        FigureCanvasAgg(figure).draw()
        self.assertEqual(center.get_color(), "red")
        self.assertEqual(center.get_marker(), "s")
        self.assertTrue(all(cap.get_markeredgecolor() == "red" for cap in caps))
        self.assertTrue(all(tuple(whisker.get_colors()[0]) == to_rgba("red") for whisker in whiskers))
        self.assertEqual([label.get_text() for label in axes.get_legend().get_texts()], ["Revised"])
        self.assertEqual(tuple(axes.get_legend().legend_handles[0].get_colors()[0]), to_rgba("red"))
        self.assertEqual(axes.get_legend_handles_labels()[1], ["Revised"])
        self.assertNotEqual(other.get_color(), "red")
        apply_style(figure, {})
        self.assertEqual(center.get_color(), original_color)
        self.assertEqual(center.get_marker(), "o")
        self.assertTrue(all(cap.get_markeredgecolor() == "gray" for cap in caps))
        self.assertTrue(all(tuple(whisker.get_colors()[0]) == to_rgba("gray") for whisker in whiskers))
        self.assertEqual(axes.get_legend_handles_labels()[1], ["Treated"])

    def test_errorbar_without_center_can_be_colored_and_renamed(self):
        figure = Figure()
        axes = figure.add_subplot()
        group = axes.errorbar([1, 2], [2, 4], yerr=.4, label="Only errors", fmt="none")
        axes.legend()
        series, = graph_series(axes)
        self.assertEqual(series.fields, {"color", "label"})
        with self.assertRaises(ValueError):
            apply_style(figure, {"series": {series.key: {"marker": "s"}}})
        apply_style(figure, {"series": {series.key: {"color": "teal", "label": "Revised"}}})
        self.assertEqual(axes.get_legend_handles_labels()[1], ["Revised"])
        self.assertEqual(tuple(group.lines[2][0].get_colors()[0]), to_rgba("teal"))

    def test_xy_series_style_persists_in_alab_and_recalculates_with_exclusions_and_export(self):
        from analisi.figure_export import export_figure
        from analisi.xy_series import XY_METHOD, style_after_parameter_change, xy_series

        frame = pd.DataFrame({
            "Time": [0.0, 1.0, 2.0, 3.0, 4.0],
            "Control": [10.0, 12.0, 15.0, 14.0, 18.0],
            "Treated": [10.0, 14.0, 19.0, 23.0, 28.0],
            "Pressure": [100.0, 105.0, 110.0, 108.0, 115.0],
        })
        options = {
            "X": "Time",
            "Y columns": ["Control", "Treated", "Pressure"],
            "Series style": {"Control": "Points", "Treated": "Line", "Pressure": "Line and points"},
            "Series side": {"Control": "Left", "Treated": "Left", "Pressure": "Right"},
            "Right title": "Pressure (kPa)",
        }
        style = {
            "title": "Hemodynamics",
            "series": {
                "xy:1:Control": {
                    "color": "#b04026", "marker": "^", "marker_size": 9.0,
                    "marker_color": "#264653", "line_style": "dotted", "width": 3.0,
                    "label": "Vehicle control",
                },
                "xy:1:Treated": {
                    "color": "#066677", "line_style": "dashed", "width": 2.5,
                    "marker": "s", "marker_size": 8.0, "marker_color": "#e9c46a",
                    "label": "Active dose",
                },
                "xy:1:Pressure": {
                    "color": "#6a4c93", "line_style": "dash-dot", "width": 2.0,
                    "marker": "D", "marker_size": 7.5, "marker_color": "#f4a261",
                    "label": "Arterial kPa",
                },
            },
            "annotations": [{"text": "Baseline", "position": [0.5, 0.5],
                             "units": "axes", "align": "center", "size": 10.0,
                             "color": "#264653"}],
        }
        legacy_style = {
            "series": {
                "xy:1:Control": {"color": "#176676", "label": "Legacy control"},
            },
        }
        dataset = Dataset(frame.copy(), analyses=[(XY_METHOD, options), (XY_METHOD, options)],
                          graph_styles={0: style, 1: legacy_style})
        with tempfile.TemporaryDirectory() as tmp:
            alab_path = Path(tmp) / "xy_styles.alab"
            save_project(alab_path, {"Study": dataset})
            reopened, _ = load_workspace(alab_path)
            restored = reopened["Study"]
            self.assertEqual(restored.graph_styles[0], style)
            self.assertEqual(restored.graph_styles[1], legacy_style)

            # Exclude one cell and edit another, then recalculate and re-apply the saved style
            restored.excluded.add((2, 1))  # exclude Control at row 2 (Time=2.0)
            restored.raw.iat[4, 2] = 31.5  # edit Treated at row 4 (Time=4.0)
            masked = restored.frame(mask_excluded=True)
            result = xy_series(masked, restored.analyses[0][1])
            apply_style(result.figure, restored.graph_styles[0])
            FigureCanvasAgg(result.figure).draw()

            left, right = result.figure.axes
            self.assertIn("Baseline", [text.get_text() for text in left.texts])
            control_line, treated_line = left.lines
            pressure_line, = right.lines
            self.assertEqual((control_line.get_linestyle(), control_line.get_marker()), ("None", "^"))
            self.assertEqual((control_line.get_markersize(), control_line.get_markerfacecolor()), (9.0, "#264653"))
            self.assertEqual((treated_line.get_linestyle(), treated_line.get_marker()), ("--", "None"))
            self.assertEqual(treated_line.get_linewidth(), 2.5)
            self.assertEqual((pressure_line.get_linestyle(), pressure_line.get_marker()), ("-.", "D"))
            self.assertEqual((pressure_line.get_linewidth(), pressure_line.get_markersize()), (2.0, 7.5))
            self.assertEqual([text.get_text() for text in left.get_legend().get_texts()],
                             ["Vehicle control", "Active dose", "Arterial kPa"])

            values_sheet = result.tables["Series values"]
            self.assertEqual(values_sheet.loc[values_sheet["Y column"] == "Control", "X"].tolist(),
                             [0.0, 1.0, 3.0, 4.0])
            self.assertEqual(values_sheet.loc[values_sheet["Y column"] == "Treated", "Y"].tolist()[-1], 31.5)

            # Use Result as Data creates a valid Dataset from Series values
            derived = Dataset(values_sheet.rename(columns=str).reset_index(drop=True))
            self.assertEqual(list(derived.frame().columns), ["Source row", "X", "Y column", "Y"])
            self.assertEqual(len(derived.frame()), 14)

            pruned_style = style_after_parameter_change(restored.graph_styles[0], {"Y columns": ["Control", "Pressure"]})
            self.assertEqual(set(pruned_style["series"]), {"xy:1:Control", "xy:1:Pressure"})

            # Export to SVG and PNG preserves formatted labels and geometry
            svg_path = Path(tmp) / "xy_formatted.svg"
            png_path = Path(tmp) / "xy_formatted.png"
            export_figure(result.figure, svg_path, {"format": "svg", "svg_text": "text"})
            export_figure(result.figure, png_path, {"format": "png", "dpi": 150})
            svg_text = svg_path.read_text(encoding="utf-8")
            self.assertIn("Vehicle control", svg_text)
            self.assertIn("Active dose", svg_text)
            self.assertIn("Arterial kPa", svg_text)
            self.assertIn("Baseline", svg_text)
            self.assertGreater(png_path.stat().st_size, 1000)
