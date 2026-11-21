"""Format Graph and the Inspector on XY graphs with Step and Bars series (needs Tk and a display)."""
from copy import deepcopy
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import to_rgba
from matplotlib.container import BarContainer
import numpy as np
import pandas as pd

from analisi.graph_dialog import GraphFormatDialog
from analisi.graph_inspector import GraphInspector
from analisi.i18n import active_language, set_language
from analisi.presentation import apply_style
from analisi.xy_series import BAR_WIDTH, XY_METHOD, xy_series


def frame():
    return pd.DataFrame({
        "Time": [0.0, 1.0, 2.0, 4.0, 5.0, 8.0],
        "Counts": [2.0, np.nan, -3.0, 4.0, 0.0, 9.0],
        "Dose": [0.0, 3.0, np.nan, 4.0, 6.0, 5.0],
        "Trend": [3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    })


def options(**update):
    return {"X": "Time", "Y columns": ["Counts", "Dose", "Trend"],
            "Series style": {"Counts": "Points", "Dose": "Step", "Trend": "Line"},
            "Series side": {"Trend": "Right"}, **update}


class EditorCase(unittest.TestCase):
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

    def use(self, code):
        previous = active_language()
        set_language(code)
        self.addCleanup(set_language, previous)

    def format_graph(self, recipe, style, drive, data=None):
        data = frame() if data is None else data
        result = xy_series(data, recipe)
        apply_style(result.figure, style)
        errors = []

        def step():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, GraphFormatDialog))
            try:
                drive(dialog)
            except Exception as error:  # reported once the modal loop returns
                errors.append(error)
                dialog.cancel()

        self.root.after(150, step)
        dialog = GraphFormatDialog(self.root, result.figure.axes[0], deepcopy(style),
                                   xy={"frame": data, "options": deepcopy(recipe)})
        if errors:
            raise errors[0]
        return dialog

    @staticmethod
    def select(dialog, column):
        dialog.series_selector.current([item.name for item in dialog.series].index(column))
        dialog._select_series()

    @staticmethod
    def width_shown(dialog):
        dialog.update_idletasks()
        return bool(dialog._bar_width_widget.grid_info())


class FormatGraphTests(EditorCase):
    def test_bars_bring_the_width_field_and_an_italian_decimal_comma_survives_an_invalid_value(self):
        self.use("it")

        def drive(dialog):
            self.assertFalse(self.width_shown(dialog), "no Bars series: no width field")
            self.select(dialog, "Counts")
            self.assertIn("Barre", dialog._draw_widget.cget("values"))
            dialog.draw_style.set("Bars")
            self.assertTrue(self.width_shown(dialog))
            for key in ("line_style", "width", "marker", "marker_size", "marker_color"):
                self.assertEqual(str(dialog._series_widgets[key].cget("state")), "disabled", key)
            self.assertNotIn("disabled", dialog._series_widgets["visible"].state())
            dialog.bar_width.set("0")
            with patch("tkinter.messagebox.showerror") as shown:
                self.assertFalse(dialog.validate())
            self.assertIn("larghezza del gruppo di barre", shown.call_args.args[1])
            self.assertIs(dialog.error_widget, dialog._bar_width_widget)
            dialog.bar_width.set("1,2")
            dialog.series_fields["color"].set("#624b91")
            dialog.ok()

        dialog = self.format_graph(options(), {}, drive)
        self.assertEqual(dialog.xy_update["Series style"]["Counts"], "Bars")
        self.assertEqual(dialog.xy_update[BAR_WIDTH], 1.2)
        bars = next(c for c in dialog.xy_result.figure.axes[0].containers if isinstance(c, BarContainer))
        self.assertTrue(np.allclose([p.get_width() for p in bars.patches], 1.2))
        self.assertEqual(bars.patches[0].get_facecolor(), to_rgba("#624b91"))
        self.assertEqual(dialog.result["series"]["xy:1:Counts"], {"color": "#624b91"})

    def test_show_box_is_saved_for_step_and_bars_and_hidden_bars_keep_their_slot(self):
        recipe = options(**{"Series style": {"Counts": "Bars", "Dose": "Step", "Trend": "Bars"}})

        def drive(dialog):
            self.assertEqual(dialog.bar_width.get(), "")
            self.select(dialog, "Trend")
            dialog.series_visible.set(False)
            self.select(dialog, "Dose")
            self.assertNotIn("disabled", dialog._series_widgets["visible"].state())
            self.assertEqual(str(dialog._series_widgets["line_style"].cget("state")), "readonly")
            self.assertEqual(str(dialog._series_widgets["marker"].cget("state")), "disabled")
            dialog.series_fields["line_style"].set("dotted")
            dialog.draw_style.set("Line")
            self.assertIn("disabled", dialog._series_widgets["visible"].state())
            dialog.draw_style.set("Step")
            dialog.ok()

        dialog = self.format_graph(recipe, {}, drive)
        self.assertEqual(dialog.result["series"], {"xy:1:Trend": {"visible": False},
                                                   "xy:1:Dose": {"line_style": "dotted"}})
        left, right = dialog.xy_result.figure.axes
        hidden = next(c for c in right.containers if isinstance(c, BarContainer))
        shown = next(c for c in left.containers if isinstance(c, BarContainer))
        self.assertFalse(any(p.get_visible() for p in hidden.patches))
        self.assertTrue(np.allclose([p.get_x() + p.get_width() / 2 for p in shown.patches],
                                    np.array([0, 2, 4, 5, 8]) - 0.2))
        self.assertEqual([t.get_text() for t in left.get_legend().get_texts()], ["Counts", "Dose"])

    def test_a_repeated_x_selects_the_bar_series_and_its_draw_style(self):
        data = pd.concat([frame(), frame().iloc[[0]]], ignore_index=True)

        def drive(dialog):
            self.select(dialog, "Counts")
            dialog.draw_style.set("Bars")
            self.select(dialog, "Trend")
            with patch("tkinter.messagebox.showerror") as shown:
                self.assertFalse(dialog.validate())
            self.assertIn("repeats X = 0", shown.call_args.args[1])
            self.assertEqual(dialog.series[dialog._series_index].name, "Counts")
            self.assertIs(dialog.error_widget, dialog._draw_widget)
            self.assertEqual(dialog.notebook.index("current"), 2)
            dialog.draw_style.set("Points")
            dialog.ok()

        dialog = self.format_graph(options(), {}, drive, data=data)
        self.assertEqual(dialog.xy_update["Series style"]["Counts"], "Points")

    def test_logarithmic_scales_on_a_bar_axis_are_refused_on_the_scale_controls(self):
        recipe = options(**{"Series style": {"Counts": "Bars", "Dose": "Step", "Trend": "Bars"}})

        def drive(dialog):
            dialog.right_scale.set("Log")
            with patch("tkinter.messagebox.showerror") as shown:
                self.assertFalse(dialog.validate())
            self.assertIn("linear right Y axis", shown.call_args.args[1])
            self.assertIs(dialog.error_widget, dialog._right_widgets["Right scale"])
            dialog.right_scale.set("Linear")
            dialog.inputs["xscale"].set("log")
            with patch("tkinter.messagebox.showerror") as shown:
                self.assertFalse(dialog.validate())
            self.assertIn("linear X axis", shown.call_args.args[1])
            self.assertIs(dialog.error_widget, dialog._axis_widgets["x"]["scale"])
            dialog.inputs["xscale"].set("linear")
            dialog.inputs["yscale"].set("log")
            with patch("tkinter.messagebox.showerror") as shown:
                self.assertFalse(dialog.validate())
            self.assertIn("linear left Y axis", shown.call_args.args[1])
            self.assertIs(dialog.error_widget, dialog._axis_widgets["y"]["scale"])
            dialog.cancel()

        dialog = self.format_graph(recipe, {}, drive)
        self.assertIsNone(dialog.result)


class InspectorTests(EditorCase):
    def open(self, recipe, style=None):
        result = xy_series(frame(), recipe)
        if style:
            apply_style(result.figure, style)
        self.run = SimpleNamespace(method=XY_METHOD, style=deepcopy(style), result=SimpleNamespace(style_warning=None))
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(result.figure, master=holder)
        panel = GraphInspector(holder, self.run, canvas, None, confirmed=lambda: self.run.style,
                               commit=self.commit, closed=lambda: None)
        self.addCleanup(panel.dispose)
        return panel, result.figure

    def commit(self, style):
        self.run.style = style

    def put(self, panel, name, value, source):
        panel.vars[name].set(value)
        panel._now(source)

    def test_bars_preview_color_and_visibility_then_cancel_and_apply(self):
        recipe = options(**{"Series style": {"Counts": "Bars", "Dose": "Step", "Trend": "Line"}})
        saved = {"series": {"xy:1:Counts": {"marker": "s"}}}
        panel, figure = self.open(recipe, saved)
        bars = next(c for c in figure.axes[0].containers if isinstance(c, BarContainer))
        panel.select_group("xy:1:Counts")
        for key in ("line_style", "width", "marker", "marker_size", "marker_color"):
            self.assertIn("disabled", panel.fields[key]["widget"].state(), key)
        self.assertNotIn("disabled", panel.fields["visible"]["widget"].state())
        self.assertEqual(panel.vars["element:marker"].get(), "Square")
        self.put(panel, "element:color", "#117733", "element:color")
        self.assertEqual(bars.patches[0].get_facecolor(), to_rgba("#117733"))
        self.put(panel, "element:visible", False, "element:visible")
        self.assertFalse(bars.patches[0].get_visible())
        self.assertEqual([t.get_text() for t in figure.axes[0].get_legend().get_texts()], ["Dose", "Trend"])
        panel.discard()
        self.assertTrue(bars.patches[0].get_visible())
        self.assertNotEqual(bars.patches[0].get_facecolor(), to_rgba("#117733"))
        self.assertEqual(self.run.style, saved)
        panel.select_group("xy:1:Counts")
        self.put(panel, "element:color", "#117733", "element:color")
        self.assertTrue(panel.apply())
        self.assertEqual(self.run.style["series"]["xy:1:Counts"], {"marker": "s", "color": "#117733"})

    def test_step_line_controls_and_a_logarithmic_x_axis_is_flagged(self):
        recipe = options(**{"Series style": {"Counts": "Bars", "Dose": "Step", "Trend": "Line"}})
        panel, figure = self.open(recipe)
        panel.select_group("xy:1:Dose")
        self.assertNotIn("disabled", panel.fields["line_style"]["widget"].state())
        self.assertNotIn("disabled", panel.fields["visible"]["widget"].state())
        self.assertIn("disabled", panel.fields["marker"]["widget"].state())
        panel.select_group("xy:1:Trend")
        self.assertIn("disabled", panel.fields["visible"]["widget"].state())
        self.put(panel, "xscale", "log", "xscale")
        self.assertIn("xscale", panel.errors)
        self.assertIn("linear X axis", panel.errors["xscale"])
        self.assertEqual(figure.axes[0].get_xscale(), "linear")


if __name__ == "__main__":
    unittest.main()
