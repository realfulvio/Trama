"""Draft, preview, apply and cancel behavior of the graph Inspector (needs Tk and a display)."""
from copy import deepcopy
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
import pandas as pd

from analisi.graph_inspector import AUTO, GraphInspector, PREVIEW_DELAY_MS
from analisi.presentation import apply_style, graph_groups
from analisi.workbench import analyse


def line_figure():
    figure = Figure(layout="constrained")
    axes = figure.add_subplot()
    axes.plot([1, 2, 3, 4], [2, 3, 5, 7], label="Control")
    axes.plot([1, 2, 3, 4], [2, 4, 8, 16], label="Drug")
    axes.scatter([1, 4], [1, 2], label="Points")
    axes.set(title="Growth", xlabel="X", ylabel="Y")
    axes.legend()
    return figure


class InspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Tk is not available: {error}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def open(self, figure=None, style=None):
        self.figure = figure or line_figure()
        self.run = SimpleNamespace(style=deepcopy(style) if style is not None else None,
                                   result=SimpleNamespace(style_warning=None))
        self.committed, self.closed = [], []
        if style:
            apply_style(self.figure, style)
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        self.addCleanup(self.root.update_idletasks)
        canvas = FigureCanvasTkAgg(self.figure, master=holder)
        panel = GraphInspector(holder, self.run, canvas, None, confirmed=lambda: self.run.style,
                               commit=self.commit, closed=lambda: self.closed.append(True))
        self.addCleanup(panel.dispose)
        return panel

    def commit(self, style):
        self.committed.append(style)
        self.run.style = style

    @staticmethod
    def put(panel, name, value, source):
        panel.vars[name].set(value)
        panel._now(source)

    def test_valid_changes_preview_in_place_and_do_not_touch_the_confirmed_style(self):
        saved = {"title": "Growth", "reference_lines": [{"axis": "y", "value": 6.0, "label": ""}]}
        panel = self.open(style=saved)
        canvas, axes = panel.canvas, self.figure.axes[0]
        panel.select_group("line:1:Drug")
        self.put(panel, "element:color", "#9b4174", "element:color")
        self.put(panel, "ymin", "1", "yrange")
        self.put(panel, "ymax", "20", "yrange")
        self.assertEqual(axes.lines[1].get_color(), "#9b4174")
        self.assertEqual(tuple(axes.get_ylim()), (1, 20))
        self.assertEqual(len(axes._tramastat_references), 1)
        self.assertIs(panel.canvas, canvas)
        self.assertEqual(self.run.style, saved)
        self.assertEqual(self.committed, [])
        self.assertTrue(panel.has_draft)

    def test_unconfirmed_pending_and_invalid_text_counts_as_a_draft(self):
        panel = self.open()
        panel.vars["title"].set("Typed but pending")
        panel._schedule("title")
        self.assertTrue(panel.has_draft)
        panel.discard()
        self.assertFalse(panel.has_draft)
        self.put(panel, "ymin", "oops", "yrange")
        self.assertTrue(panel.has_draft)

    def test_invalid_numbers_keep_the_last_valid_preview_and_flag_the_field(self):
        panel = self.open()
        axes = self.figure.axes[0]
        self.put(panel, "ymin", "1", "yrange")
        self.put(panel, "ymax", "20", "yrange")
        for low, high, message in (("20", "1", "smaller"), ("1", "", "both limits"), ("a", "5", "number")):
            self.put(panel, "ymin", low, "yrange")
            self.put(panel, "ymax", high, "yrange")
            self.assertIn(message, panel.errors["yrange"])
            self.assertTrue(panel.messages["yrange"].winfo_manager())
            self.assertEqual(tuple(axes.get_ylim()), (1, 20))
            self.assertFalse(panel.apply())
            self.assertEqual(self.committed, [])
        self.put(panel, "ymin", "2", "yrange")
        self.put(panel, "ymax", "9", "yrange")
        self.assertNotIn("yrange", panel.errors)
        self.assertEqual(tuple(axes.get_ylim()), (2, 9))

    def test_apply_stores_a_validated_copy_and_keeps_keys_the_panel_does_not_manage(self):
        saved = {"title": "Growth", "tick_size": 9, "axis": {"y": {"step": 5.0, "min": 0.0, "max": 20.0}},
                 "reference_lines": [{"axis": "y", "value": 6.0, "label": "Target"}]}
        panel = self.open(style=saved)
        self.put(panel, "ymin", "1", "yrange")
        self.put(panel, "ymax", "30", "yrange")
        panel.vars["grid"].set(True)
        panel._now("grid")
        self.assertTrue(panel.apply())
        stored, = self.committed
        self.assertEqual(stored["axis"]["y"], {"step": 5.0, "min": 1.0, "max": 30.0})
        self.assertEqual((stored["tick_size"], stored["reference_lines"], stored["title"], stored["grid"]),
                         (9, saved["reference_lines"], "Growth", True))
        self.assertIsNot(stored, panel.draft)
        self.assertFalse(panel.has_draft)

    def test_cancel_restores_the_confirmed_style_and_closes(self):
        saved = {"title": "Growth"}
        panel = self.open(style=saved)
        axes = self.figure.axes[0]
        before = tuple(axes.get_ylim()), [line.get_color() for line in axes.lines]
        panel.select_group("line:1:Drug")
        self.put(panel, "element:color", "#9b4174", "element:color")
        self.put(panel, "title", "Changed", "title")
        self.put(panel, "ymin", "1", "yrange")
        self.put(panel, "ymax", "20", "yrange")
        self.assertEqual(axes.get_title(), "Changed")
        panel.cancel()
        self.assertEqual(self.closed, [True])
        self.assertEqual((tuple(axes.get_ylim()), [line.get_color() for line in axes.lines]), before)
        self.assertEqual(axes.get_title(), "Growth")
        self.assertEqual(self.run.style, saved)
        self.assertEqual(panel.draft, saved)

    def test_escape_cancels_from_any_control(self):
        panel = self.open()
        self.put(panel, "title", "Changed", "title")
        controls = panel._controls(panel)
        self.assertTrue(controls and all(str(panel) in control.bindtags() for control in controls))
        self.assertEqual(panel._escape(None), "break")
        self.assertEqual(self.closed, [True])
        self.assertEqual(self.figure.axes[0].get_title(), "Growth")

    def test_reset_section_removes_only_that_sections_settings(self):
        saved = {"title": "Growth", "xlabel": "Days", "grid": True, "legend": "upper left",
                 "tick_size": 9, "series": {"line:1:Drug": {"color": "#9b4174", "width": 3.0}},
                 "axis": {"y": {"min": 1.0, "max": 20.0, "step": 5.0}},
                 "reference_lines": [{"axis": "y", "value": 6.0, "label": ""}]}
        panel = self.open(style=saved)
        panel.reset_section("axes")
        self.assertEqual(panel.draft["axis"], {"y": {"step": 5.0}})
        self.assertNotIn("xlabel", panel.draft)
        self.assertEqual((panel.draft["title"], panel.draft["grid"], panel.draft["legend"]), ("Growth", True, "upper left"))
        self.assertIn("series", panel.draft)
        self.assertEqual(self.figure.axes[0].get_xlabel(), "X")
        panel.reset_section("page")
        self.assertTrue({"title", "grid", "legend"}.isdisjoint(panel.draft))
        self.assertEqual(panel.draft["series"], saved["series"])
        panel.reset_section("data")
        self.assertNotIn("series", panel.draft)
        self.assertEqual((panel.draft["tick_size"], panel.draft["reference_lines"]),
                         (9, saved["reference_lines"]))
        self.assertEqual(self.run.style, saved)
        self.assertEqual(to_hex(self.figure.axes[0].lines[1].get_color()), "#ff7f0e")

    def test_automatic_values_follow_the_graph_and_equal_text_is_not_stored(self):
        panel = self.open()
        self.assertEqual(panel.vars["title"].get(), "Growth")
        self.put(panel, "title", "Other", "title")
        self.assertEqual(panel.draft["title"], "Other")
        self.put(panel, "title", "Growth", "title")
        self.assertNotIn("title", panel.draft)
        self.put(panel, "legend", "upper left", "legend")
        self.put(panel, "legend", AUTO, "legend")
        self.assertNotIn("legend", panel.draft)
        self.put(panel, "ymin", "", "yrange")
        self.assertNotIn("axis", panel.draft)

    def test_only_properties_the_series_accepts_are_shown(self):
        panel = self.open()
        self.root.update()
        panel.select_group("scatter:1:Points")
        shown = {key for key, field in panel.fields.items() if field["widget"].winfo_manager()}
        self.assertEqual(shown, {"label", "color", "marker", "marker_size"})
        panel.select_group("line:1:Control")
        shown = {key for key, field in panel.fields.items() if field["widget"].winfo_manager()}
        self.assertEqual(shown, {"label", "color", "line_style", "width", "marker", "marker_size", "marker_color"})
        self.put(panel, "element:width", "99", "element:width")
        self.assertIn("element:width", panel.errors)
        self.put(panel, "element:width", "2", "element:width")
        self.put(panel, "element:line_style", "dashed", "element:line_style")
        self.assertEqual(panel.draft["series"]["line:1:Control"], {"width": 2.0, "line_style": "dashed"})
        self.assertEqual(self.figure.axes[0].lines[0].get_linestyle(), "--")

    def test_typing_uses_one_scheduled_preview_that_is_cancelled_with_the_panel(self):
        panel = self.open()
        panel.vars["title"].set("T")
        panel._schedule("title")
        first = panel._after
        panel.vars["title"].set("Ti")
        panel._schedule("title")
        self.assertNotEqual(panel._after, first)
        self.assertEqual(panel._due, ["title"])
        self.assertEqual(self.figure.axes[0].get_title(), "Growth")
        self.root.after(PREVIEW_DELAY_MS + 200, self.root.quit)
        self.root.mainloop()
        self.assertEqual(self.figure.axes[0].get_title(), "Ti")
        self.assertIsNone(panel._after)
        panel._schedule("title")
        panel.dispose()
        self.assertIsNone(panel._after)
        self.assertEqual(self.run.style, None)
        self.assertEqual(self.figure.axes[0].get_title(), "Growth")

    def test_busy_panel_ignores_edits_and_keeps_the_preview(self):
        panel = self.open()
        self.put(panel, "title", "Preview", "title")
        panel.set_busy("Calculation in progress…")
        self.assertIn("disabled", panel.apply_button.state())
        self.put(panel, "title", "Ignored", "title")
        self.assertEqual(self.figure.axes[0].get_title(), "Preview")
        self.assertFalse(panel.apply())
        panel.set_busy(None)
        self.assertNotIn("disabled", panel.apply_button.state())
        self.assertTrue(panel.apply())

    def test_distribution_graphs_list_groups_in_plot_order_and_reset_only_their_style(self):
        frame = pd.DataFrame({"Control": [1, 2, 3, 4, 5, 6, 7, 30.], "Drug A": [4, 5, 6, 7, 8, 9, 10, 11.]})
        result = analyse("Box / violin plot", frame, {"Input": "Separate columns", "Variables": list(frame),
                                                      "Style": "Box"})
        saved = {"title": "Box", "groups": {"box:column:Control": {"visible": False}}}
        panel = self.open(result.figure, saved)
        self.assertEqual([item["name"] for item in panel.elements], ["Control", "Drug A"])
        self.assertEqual(panel.current["key"], "box:column:Control")
        self.assertFalse(panel.vars["element:visible"].get())
        panel.select_group("box:column:Drug A")
        self.put(panel, "element:color", "#9b4174", "element:color")
        self.assertEqual(panel.draft["groups"]["box:column:Drug A"], {"color": "#9b4174"})
        panel.select_group("box:column:Control")
        self.put(panel, "element:visible", True, "element:visible")
        self.assertNotIn("box:column:Control", panel.draft["groups"])
        self.assertTrue(all(artist.get_visible() for artist, _ in graph_groups(result.figure.axes[0])[0].artists))
        panel.reset_section("data")
        self.assertEqual(panel.draft, {"title": "Box"})

    def test_xy_series_inspector_and_dialog_enable_only_active_structure_controls_and_preserve_saved_values(self):
        from unittest.mock import patch
        from analisi.graph_dialog import GraphFormatDialog
        from analisi.xy_series import XY_METHOD, xy_series

        frame = pd.DataFrame({
            "X": [0.0, 1.0, 2.0, 3.0],
            "PointsCol": [2.0, 4.0, 6.0, 8.0],
            "LineCol": [1.0, 3.0, 5.0, 7.0],
            "BothCol": [10.0, 20.0, 30.0, 40.0],
        })
        options = {
            "X": "X",
            "Y columns": ["PointsCol", "LineCol", "BothCol"],
            "Series style": {"PointsCol": "Points", "LineCol": "Line", "BothCol": "Line and points"},
            "Series side": {"PointsCol": "Left", "LineCol": "Left", "BothCol": "Right"},
        }
        saved = {
            "series": {
                "xy:1:PointsCol": {"line_style": "dashed", "width": 3.0, "marker": "^", "marker_size": 9.0},
                "xy:1:LineCol": {"marker": "s", "marker_size": 8.0, "marker_color": "#264653", "line_style": "dotted"},
                "xy:1:BothCol": {"line_style": "dash-dot", "width": 2.5, "marker": "D", "marker_size": 7.5},
            }
        }
        result = xy_series(frame, options)
        apply_style(result.figure, saved)
        self.figure = result.figure
        self.run = SimpleNamespace(method=XY_METHOD, style=deepcopy(saved), result=SimpleNamespace(style_warning=None))
        self.committed, self.closed = [], []
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(self.figure, master=holder)
        panel = GraphInspector(holder, self.run, canvas, None, confirmed=lambda: self.run.style,
                               commit=self.commit, closed=lambda: self.closed.append(True))
        self.addCleanup(panel.dispose)

        # PointsCol: line controls disabled but showing saved values; marker controls enabled
        panel.select_group("xy:1:PointsCol")
        self.assertIn("disabled", panel.fields["line_style"]["widget"].state())
        self.assertIn("disabled", panel.fields["width"]["widget"].state())
        self.assertNotIn("disabled", panel.fields["marker"]["widget"].state())
        self.assertNotIn("disabled", panel.fields["marker_size"]["widget"].state())
        self.assertEqual(panel.vars["element:line_style"].get(), "dashed")
        self.assertEqual(panel.vars["element:width"].get(), "3.0")
        self.assertIn("No symbol", panel.choices["element:marker"].combobox.cget("values"))

        # Edit active color on PointsCol: inactive line_style and width remain in draft
        self.put(panel, "element:color", "#b04026", "element:color")
        self.assertEqual(panel.draft["series"]["xy:1:PointsCol"],
                         {"line_style": "dashed", "width": 3.0, "marker": "^", "marker_size": 9.0, "color": "#b04026"})

        # LineCol: marker controls disabled (including Pick button), line controls enabled
        panel.select_group("xy:1:LineCol")
        self.assertNotIn("disabled", panel.fields["line_style"]["widget"].state())
        self.assertNotIn("disabled", panel.fields["width"]["widget"].state())
        self.assertIn("disabled", panel.fields["marker"]["widget"].state())
        self.assertIn("disabled", panel.fields["marker_size"]["widget"].state())
        self.assertIn("disabled", panel.fields["marker_color"]["widget"].state())
        self.assertTrue(all("disabled" in w.state() for w in panel.fields["marker_color"]["shown"]
                            if isinstance(w, ttk.Button)))
        self.assertEqual(panel.vars["element:marker"].get(), "Square")

        # BothCol: all line and marker controls enabled
        panel.select_group("xy:1:BothCol")
        for key in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color"):
            self.assertNotIn("disabled", panel.fields[key]["widget"].state(), key)

        # Reset data section restores recipe defaults
        panel.reset_section("data")
        self.assertNotIn("series", panel.draft)
        left_axes, right_axes = self.figure.axes
        self.assertEqual((left_axes.lines[0].get_linestyle(), left_axes.lines[0].get_marker()), ("None", "o"))
        self.assertEqual((left_axes.lines[1].get_linestyle(), left_axes.lines[1].get_marker()), ("-", "None"))
        self.assertEqual((right_axes.lines[0].get_linestyle(), right_axes.lines[0].get_marker()), ("-", "o"))

        # Drive real GraphFormatDialog on the same XY figure
        errors = []

        def drive(dialog):
            try:
                self.assertEqual(str(dialog._series_widgets["line_style"].cget("state")), "disabled")
                self.assertEqual(str(dialog._series_widgets["width"].cget("state")), "disabled")
                self.assertEqual(str(dialog._series_widgets["marker"].cget("state")), "readonly")
                self.assertEqual(dialog.series_fields["line_style"].get(), "dashed")
                self.assertEqual(dialog.series_fields["width"].get(), "3.0")
                # Switch draw_style live to Line and points -> line controls become enabled immediately
                dialog.draw_style.set("Line and points")
                self.assertEqual(str(dialog._series_widgets["line_style"].cget("state")), "readonly")
                self.assertEqual(str(dialog._series_widgets["width"].cget("state")), "normal")
                # Trigger validation error on width -> dialog stays open and focuses width widget
                dialog.series_fields["width"].set("99")
                with patch("tkinter.messagebox.showerror") as shown:
                    self.assertFalse(dialog.validate())
                    self.assertIn("0.1 and 72", shown.call_args.args[1])
                self.assertIs(dialog.error_widget, dialog._series_widgets["width"])
                dialog.series_fields["width"].set("2.5")
                dialog.ok()
            except Exception as exc:
                errors.append(exc)
                dialog.cancel()

        self.root.after(150, lambda: drive(next(w for w in self.root.winfo_children()
                                                if isinstance(w, GraphFormatDialog))))
        dialog = GraphFormatDialog(self.root, left_axes, deepcopy(saved),
                                   xy={"frame": frame, "options": deepcopy(options)})
        if errors:
            raise errors[0]
        self.assertEqual(dialog.xy_update["Series style"]["PointsCol"], "Line and points")
        self.assertEqual(dialog.result["series"]["xy:1:PointsCol"]["width"], 2.5)
        self.assertEqual(dialog.result["series"]["xy:1:PointsCol"]["line_style"], "dashed")



if __name__ == "__main__":
    unittest.main()
