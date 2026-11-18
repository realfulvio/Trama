"""Tk tests for the axis breaks editor, Format Graph and the Inspector, plus the EN/IT catalog of the feature."""
from copy import deepcopy
from types import SimpleNamespace
import re
import unittest

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from analisi import axis_breaks as ab
from analisi import i18n
from analisi.axis_breaks import AXIS_BREAKS, axis_breaks_reason, segment_axes, suggest_axis_breaks
from analisi.axis_breaks_dialog import AxisBreaksDialog, breaks_summary, translate_breaks_error
from analisi.graph_dialog import GraphFormatDialog
from analisi.graph_inspector import GraphInspector
from analisi.i18n import active_language, set_language, tr
from analisi.presentation import apply_style
from analisi.xy_errors import xy_errors
from analisi.xy_series import XY_METHOD, xy_series

FRAME = pd.DataFrame({
    "t": [0, 1, 2, 3, 4, 6, 7, 10, 11, 12, 18, 20, 22],
    "a": [1, 2, 2.7, 3.6, 4.5, 11, 15, 21, 22, 24, 27, 29, 31],
    "b": [2, 5, 8, np.nan, 9, 12, 14, 24, 27, 30, 25, 28, 34],
    "down": [.2, .2, .4, .2, .3, .4, .5, .2, .5, .2, .6, .8, 1.2],
    "up": [.6, .4, .7, .6, .8, .6, .3, .6, .7, .4, .9, .7, 1.6],
})
SERIES = {"X": "t", "Y columns": ["a", "b"], "Series style": {"a": "Line and points", "b": "Points"}}
RIGHT = dict(SERIES, **{"Series side": {"a": "Left", "b": "Right"}})
ERRORS = {"X": "t", "Y": "a", "Y lower error": "down", "Y upper error": "up", "Y error values": "Distances"}
X_BREAKS = {"axis": "x", "gap": 0.04, "segments": [
    {"low": 0, "high": 4, "share": 35, "major_step": 2},
    {"low": 10, "high": 12, "share": 30, "major_step": 1},
    {"low": 18, "high": 22, "share": 35, "major_step": 2}]}
Y_BREAKS = {"axis": "y", "gap": 0.05, "segments": [
    {"low": 0, "high": 10, "share": 42, "major_step": 5},
    {"low": 20, "high": 36, "share": 58, "major_step": 4}]}


def _find(parent, cls):
    for child in parent.winfo_children():
        if isinstance(child, cls):
            return child
        found = _find(child, cls)
        if found is not None:
            return found
    return None


class CatalogTests(unittest.TestCase):
    def test_both_languages_have_the_same_keys_and_placeholders(self):
        english = {key: text for key, text in i18n._EN.items() if key.startswith("axis_breaks.")}
        italian = {key: text for key, text in i18n._IT.items() if key.startswith("axis_breaks.")}
        self.assertEqual(set(english), set(italian))
        holes = lambda text: sorted(re.findall(r"\{(\w+)", text))
        for key in english:
            self.assertEqual(holes(english[key]), holes(italian[key]), key)

    def test_every_engine_message_has_an_entry_in_each_language(self):
        names = [name for name in dir(ab) if re.fullmatch(r"[MP]_[A-Z_]+", name)]
        self.assertGreaterEqual(len(names), 20)
        for name in names:
            key = "axis_breaks.error." + name.lower()
            self.assertEqual(i18n._EN[key], getattr(ab, name), name)
            self.assertIn(key, i18n._IT)

    def test_engine_errors_are_translated_with_their_values(self):
        previous = active_language()
        self.addCleanup(set_language, previous)
        set_language("it")
        with self.assertRaises(ab.AxisBreakError) as caught:
            ab.normalise_axis_breaks({"axis": "x", "gap": 0.04, "segments": [
                {"low": 0, "high": 4, "share": 50, "major_step": None},
                {"low": 10, "high": 12, "share": 40, "major_step": None}]})
        text = translate_breaks_error(caught.exception)
        self.assertNotEqual(text, str(caught.exception))
        self.assertIn("90", text)
        self.assertEqual(translate_breaks_error(ValueError("Something unknown")), "Something unknown")


class StatusWarningTests(unittest.TestCase):
    def test_saved_breaks_that_cannot_be_drawn_become_a_translated_warning(self):
        from tramastat import App

        previous = active_language()
        self.addCleanup(set_language, previous)
        figure = xy_series(FRAME, RIGHT).figure
        apply_style(figure, {AXIS_BREAKS: X_BREAKS})
        set_language("en")
        self.assertEqual(App.breaks_warning(figure, {AXIS_BREAKS: X_BREAKS}),
                         "Axis breaks are saved but not drawn: " + ab.P_RIGHT)
        set_language("it")
        self.assertIn("non disegnate", App.breaks_warning(figure, {AXIS_BREAKS: X_BREAKS}))
        self.assertIsNone(App.breaks_warning(figure, {}))
        self.assertIsNone(App.breaks_warning(None, {AXIS_BREAKS: X_BREAKS}))
        drawn = xy_series(FRAME, SERIES).figure
        apply_style(drawn, {AXIS_BREAKS: X_BREAKS})
        self.assertIsNone(App.breaks_warning(drawn, {AXIS_BREAKS: X_BREAKS}))


class SuggestionTests(unittest.TestCase):
    def test_cuts_follow_the_widest_empty_stretches(self):
        axes = xy_series(FRAME, SERIES).figure.axes[0]
        record = suggest_axis_breaks(axes, "x", 3)
        self.assertEqual(ab.normalise_axis_breaks(record), record)
        limits = [(segment["low"], segment["high"]) for segment in record["segments"]]
        self.assertEqual(limits, [(-1.0, 8.0), (9.0, 13.0), (17.0, 23.0)])
        self.assertAlmostEqual(sum(segment["share"] for segment in record["segments"]), 100)
        two = suggest_axis_breaks(axes, "y", 2)
        self.assertEqual([(s["low"], s["high"]) for s in two["segments"]], [(0.0, 16.0), (20.0, 35.0)])

    def test_every_suggested_segment_keeps_at_least_fifteen_percent(self):
        axes = xy_series(FRAME, SERIES).figure.axes[0]
        record = suggest_axis_breaks(axes, "y", 3)
        self.assertGreaterEqual(min(segment["share"] for segment in record["segments"]), 15)
        self.assertAlmostEqual(sum(segment["share"] for segment in record["segments"]), 100)

    def test_error_bars_are_included_and_the_result_draws(self):
        figure = xy_errors(FRAME, ERRORS).figure
        record = suggest_axis_breaks(figure.axes[0], "y", 2)
        self.assertLess(record["segments"][0]["low"], FRAME["a"].min() - FRAME["down"].iloc[0] + 1e-9)
        apply_style(figure, {AXIS_BREAKS: record})
        self.assertEqual(len(segment_axes(figure)), 2)
        self.assertIsNone(axis_breaks_reason(figure))

    def test_data_that_cannot_be_cut_gives_none(self):
        axes = xy_series(pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]}), {"X": "x", "Y columns": ["y"]}).figure.axes[0]
        self.assertIsNone(suggest_axis_breaks(axes, "x", 3))
        self.assertIsNone(suggest_axis_breaks(axes, "x", 4))


class GuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            cls.root = tk.Tk()
        except Exception as error:
            raise unittest.SkipTest(f"Tk is not available: {error}")
        cls.root.geometry("1024x768+0+0")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def language(self, code):
        previous = active_language()
        set_language(code)
        self.addCleanup(set_language, previous)

    def modal(self, parent, cls, action, errors):
        """Run ``action(dialog)`` once the modal dialog of class ``cls`` is open under ``parent``."""
        def step():
            dialog = _find(parent, cls)
            if dialog is None:
                errors.append(AssertionError(f"{cls.__name__} did not open"))
                return
            try:
                action(dialog)
            except Exception as error:
                errors.append(error)
                if dialog.winfo_exists():
                    dialog.cancel()

        self.root.after(120, step)

    @staticmethod
    def figure(options=SERIES, style=None):
        figure = xy_series(FRAME, options).figure
        apply_style(figure, style or {})
        return figure

    @staticmethod
    def preview_for(figure, confirmed=None):
        """The preview contract of the editor: ``{}`` no breaks, ``None`` the confirmed look, ValueError if not shown."""
        seen = []

        def preview(record):
            seen.append(deepcopy(record))
            style = {AXIS_BREAKS: confirmed} if (record is None and confirmed) else ({AXIS_BREAKS: record} if record else {})
            apply_style(figure, style)
            reason = axis_breaks_reason(figure) if record else None
            if reason:
                apply_style(figure, {AXIS_BREAKS: confirmed} if confirmed else {})
                raise ValueError(reason)

        preview.seen = seen
        return preview

    def open_editor(self, figure, record, action, **keywords):
        errors = []
        self.modal(self.root, AxisBreaksDialog, action, errors)
        dialog = AxisBreaksDialog(self.root, figure.axes[0], record, **keywords)
        if errors:
            raise errors[0]
        return dialog


class EditorTests(GuiCase):
    def test_choosing_an_axis_suggests_rows_and_the_total_follows(self):
        self.language("en")
        figure = self.figure()
        seen = {}

        def action(dialog):
            self.assertEqual(dialog.axis.get(), "")
            self.assertIn("disabled", dialog.widgets["gap"].state())
            dialog.axis.set("x")
            seen["rows"] = [[dialog.vars[(row, name)].get() for name in ("low", "high", "share")] for row in range(3)]
            seen["total"] = dialog.total.cget("text")
            self.assertNotIn("disabled", dialog.widgets["segments.2.high"].state())
            dialog.count.set("2")
            self.assertIn("disabled", dialog.widgets["segments.2.high"].state())
            dialog.vars[(0, "share")].set("10")
            seen["bad_total"] = dialog.total.cget("text")
            dialog.cancel()

        dialog = self.open_editor(figure, {}, action)
        self.assertIsNone(dialog.result)
        self.assertEqual(seen["rows"][0][:2], ["-1", "8"])
        self.assertEqual(seen["total"], tr("axis_breaks.total", total="100"))
        self.assertNotEqual(seen["bad_total"], seen["total"])

    def test_typed_decimal_commas_give_the_canonical_record(self):
        self.language("it")
        figure = self.figure()
        preview = self.preview_for(figure)

        def action(dialog):
            self.assertEqual(dialog.title(), "Interruzioni asse")
            dialog.axis.set("y")
            dialog.count.set("2")
            for row, values in enumerate((("0", "10", "42", "5"), ("20", "36,5", "58", ""))):
                for name, value in zip(("low", "high", "share", "major_step"), values):
                    dialog.vars[(row, name)].set(value)
            dialog.gap.set("0,05")
            dialog.ok()

        dialog = self.open_editor(figure, {}, action, preview=preview)
        self.assertEqual(dialog.result, {"axis": "y", "gap": 0.05, "segments": [
            {"low": 0.0, "high": 10.0, "share": 42.0, "major_step": 5.0},
            {"low": 20.0, "high": 36.5, "share": 58.0, "major_step": None}]})
        self.assertEqual(len(segment_axes(figure)), 2)
        self.assertEqual(breaks_summary(dialog.result), "Asse Y, 2 segmenti")

    def test_a_bad_field_is_named_focused_and_leaves_the_editor_open(self):
        self.language("en")
        figure = self.figure()
        preview = self.preview_for(figure, X_BREAKS)

        def action(dialog):
            dialog.vars[(1, "low")].set("abc")
            self.assertEqual(dialog.ok(), "break")
            self.assertTrue(dialog.winfo_exists())
            self.assertIs(dialog.error_widget, dialog.widgets["segments.1.low"])
            self.assertIn("Segment 2", dialog.problem.cget("text"))
            self.assertEqual(preview.seen, [])
            dialog.vars[(1, "low")].set("10")
            dialog.vars[(1, "share")].set("20")
            dialog.preview()
            self.assertIs(dialog.error_widget, dialog.widgets["segments.2.share"])
            self.assertIn("100", dialog.problem.cget("text"))
            dialog.vars[(1, "share")].set("30")
            dialog.gap.set("0.5")
            dialog.preview()
            self.assertIs(dialog.error_widget, dialog.widgets["gap"])
            dialog.gap.set("0.04")
            dialog.ok()

        dialog = self.open_editor(figure, X_BREAKS, action, preview=preview)
        self.assertEqual(dialog.result, ab.normalise_axis_breaks(X_BREAKS))

    def test_off_returns_an_empty_record_and_removes_the_panels(self):
        self.language("en")
        figure = self.figure(style={AXIS_BREAKS: X_BREAKS})
        preview = self.preview_for(figure, X_BREAKS)

        def action(dialog):
            dialog.axis.set("")
            self.assertIn("disabled", dialog.widgets["gap"].state())
            dialog.ok()

        dialog = self.open_editor(figure, X_BREAKS, action, preview=preview)
        self.assertEqual(dialog.result, {})
        self.assertEqual(segment_axes(figure), [])

    def test_cancel_after_a_preview_goes_back_to_the_confirmed_look(self):
        self.language("en")
        figure = self.figure(style={AXIS_BREAKS: X_BREAKS})
        preview = self.preview_for(figure, X_BREAKS)

        def action(dialog):
            dialog.axis.set("y")
            self.assertTrue(dialog.preview())
            self.assertEqual(segment_axes(figure)[0].get_xlim(), figure.axes[0].get_xlim())
            self.assertEqual(ab.panel_scope(segment_axes(figure)[0])[0], "y")
            dialog.cancel()

        dialog = self.open_editor(figure, X_BREAKS, action, preview=preview)
        self.assertIsNone(dialog.result)
        self.assertIsNone(preview.seen[-1])
        self.assertEqual(ab.panel_scope(segment_axes(figure)[0])[0], "x")

    def test_a_graph_that_cannot_show_the_breaks_explains_why(self):
        self.language("en")
        figure = self.figure(RIGHT)
        preview = self.preview_for(figure)

        def action(dialog):
            dialog.axis.set("y")
            self.assertFalse(dialog.preview())
            self.assertEqual(dialog.problem.cget("text"), ab.P_RIGHT)
            dialog.cancel()

        self.open_editor(figure, {}, action, preview=preview)
        self.assertEqual(segment_axes(figure), [])

    def test_busy_calculation_blocks_the_buttons(self):
        self.language("en")
        figure = self.figure()
        preview = self.preview_for(figure)

        def action(dialog):
            dialog.axis.set("x")
            self.assertFalse(dialog.preview())
            self.assertEqual(dialog.problem.cget("text"), tr("axis_breaks.error.busy"))
            dialog.cancel()

        self.open_editor(figure, {}, action, preview=preview, busy=lambda: True)
        self.assertEqual(preview.seen, [])

    def test_suggest_button_reports_data_that_cannot_be_cut(self):
        self.language("en")
        figure = xy_series(pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]}), {"X": "x", "Y columns": ["y"]}).figure
        apply_style(figure, {})

        def action(dialog):
            dialog.axis.set("x")
            dialog.suggest()
            self.assertEqual(dialog.problem.cget("text"), tr("axis_breaks.error.no_suggestion"))
            dialog.cancel()

        self.open_editor(figure, {}, action)


class FormatGraphTests(GuiCase):
    def format_dialog(self, options, style, action):
        figure = self.figure(options, style)
        errors = []
        self.modal(self.root, GraphFormatDialog, lambda dialog: action(dialog, figure), errors)
        dialog = GraphFormatDialog(self.root, figure.axes[0], deepcopy(style),
                                   xy={"frame": FRAME, "options": dict(options)})
        if errors:
            raise errors[0]
        return figure, dialog

    def test_the_axes_tab_edits_the_breaks_and_applies_them_to_the_new_graph(self):
        self.language("en")
        seen = {}

        def action(dialog, figure):
            seen["summary"] = dialog.breaks_summary.cget("text")
            self.assertEqual(dialog.breaks_note.cget("text"), "")

            def inner(editor):
                editor.axis.set("x")
                self.assertTrue(editor.preview())
                seen["live"] = len(segment_axes(figure))
                editor.ok()

            self.modal(dialog, AxisBreaksDialog, inner, seen.setdefault("errors", []))
            dialog._edit_axis_breaks()
            seen["after"] = dialog.breaks_summary.cget("text")
            seen["states"] = tuple(str(widget.cget("state")) for widget in (
                dialog._axis_widgets["x"]["min"], dialog._axis_widgets["x"]["scale"], dialog._axis_widgets["y"]["min"]))
            dialog.ok()

        figure, dialog = self.format_dialog(SERIES, {}, action)
        self.assertEqual(seen.get("errors"), [])
        self.assertEqual(seen["summary"], tr("axis_breaks.summary_none"))
        self.assertEqual(seen["live"], 3)
        self.assertEqual(seen["after"], tr("axis_breaks.summary", axis="X", count=3))
        self.assertEqual(seen["states"], ("disabled", "disabled", "normal"))
        self.assertEqual(dialog.result[AXIS_BREAKS]["axis"], "x")
        self.assertEqual(len(segment_axes(dialog.xy_result.figure)), 3)

    def test_cancel_puts_the_confirmed_graph_back(self):
        self.language("en")

        def action(dialog, figure):
            def inner(editor):
                editor.axis.set("y")
                editor.preview()
                editor.ok()

            self.modal(dialog, AxisBreaksDialog, inner, [])
            dialog._edit_axis_breaks()
            self.assertEqual(ab.panel_scope(segment_axes(figure)[0])[0], "y")
            dialog.cancel()

        figure, dialog = self.format_dialog(SERIES, {AXIS_BREAKS: X_BREAKS}, action)
        self.assertIsNone(dialog.result)
        self.assertEqual(ab.panel_scope(segment_axes(figure)[0])[0], "x")

    def test_removing_the_breaks_returns_the_limits_and_the_fields(self):
        self.language("en")
        limits = {}

        def action(dialog, figure):
            limits["before"] = figure.axes[0].get_xlim()

            def inner(editor):
                editor.axis.set("")
                editor.ok()

            self.modal(dialog, AxisBreaksDialog, inner, [])
            dialog._edit_axis_breaks()
            limits["state"] = str(dialog._axis_widgets["x"]["min"].cget("state"))
            dialog.ok()

        figure, dialog = self.format_dialog(SERIES, {AXIS_BREAKS: X_BREAKS}, action)
        self.assertEqual(limits["state"], "normal")
        self.assertNotIn(AXIS_BREAKS, dialog.result)
        self.assertEqual(segment_axes(dialog.xy_result.figure), [])
        self.assertEqual(dialog.xy_result.figure.axes[0].get_xlim(), xy_series(FRAME, SERIES).figure.axes[0].get_xlim())

    def test_breaks_chosen_here_that_cannot_be_drawn_stop_the_apply_and_say_why(self):
        self.language("en")
        shown = []

        def action(dialog, figure):
            dialog.right_scale.set("Linear")
            dialog._axis_breaks = deepcopy(X_BREAKS)
            from tkinter import messagebox
            original = messagebox.showerror
            messagebox.showerror = lambda title, message, **_: shown.append(message)
            self.addCleanup(setattr, messagebox, "showerror", original)
            self.assertFalse(dialog.validate())
            self.assertIs(dialog.error_widget, dialog.breaks_button)
            dialog.cancel()

        self.format_dialog(RIGHT, {}, action)
        self.assertEqual(shown, [ab.P_RIGHT])

    def test_saved_breaks_that_cannot_be_drawn_are_kept_and_declared(self):
        self.language("it")
        notes = []

        def action(dialog, figure):
            notes.append(dialog.breaks_note.cget("text"))
            self.assertTrue(dialog.validate())
            dialog.ok()

        figure, dialog = self.format_dialog(RIGHT, {AXIS_BREAKS: X_BREAKS}, action)
        self.assertEqual(dialog.result[AXIS_BREAKS], X_BREAKS)
        self.assertIn("salvate ma non disegnate", notes[0])
        self.assertIn("asse Y destro", notes[0])

    def test_reset_removes_the_breaks_and_the_graph_without_them_returns(self):
        self.language("en")

        def action(dialog, figure):
            dialog._reset()

        figure, dialog = self.format_dialog(SERIES, {AXIS_BREAKS: X_BREAKS}, action)
        self.assertNotIn(AXIS_BREAKS, dialog.result)
        self.assertEqual(segment_axes(dialog.xy_result.figure), [])

    def test_the_button_is_missing_where_breaks_do_not_apply(self):
        self.language("en")
        from analisi.category_graphs import category_graph

        figure = category_graph(pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]}), {"Variables": ["A", "B"]}).figure
        apply_style(figure, {})
        errors = []

        def action(dialog):
            self.assertFalse(hasattr(dialog, "breaks_button"))
            dialog.cancel()

        self.modal(self.root, GraphFormatDialog, action, errors)
        GraphFormatDialog(self.root, figure.axes[0], {})
        if errors:
            raise errors[0]


class InspectorTests(GuiCase):
    def inspector(self, options=SERIES, confirmed=None):
        from tkinter import ttk

        figure = self.figure(options, confirmed)
        run = SimpleNamespace(method=XY_METHOD, style=deepcopy(confirmed or {}),
                              result=SimpleNamespace(figure=figure, style_warning=None))
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(figure, master=holder)
        committed = []
        inspector = GraphInspector(holder, run, canvas, None, confirmed=lambda: run.style, commit=committed.append,
                                   closed=lambda: None)
        self.addCleanup(inspector.dispose)
        return figure, inspector, committed

    def test_the_axes_section_edits_applies_and_cancels_the_breaks(self):
        self.language("en")
        figure, inspector, committed = self.inspector()
        self.assertIn("axis_breaks", inspector.widgets)
        errors = []

        def choose(editor):
            editor.axis.set("x")
            self.assertTrue(editor.preview())
            editor.ok()

        self.modal(inspector, AxisBreaksDialog, choose, errors)
        inspector._edit_axis_breaks()
        self.assertEqual(errors, [])
        self.assertEqual(inspector.draft[AXIS_BREAKS]["axis"], "x")
        self.assertEqual(len(segment_axes(figure)), 3)
        self.assertIn("disabled", inspector.widgets["xmin"].state())
        self.assertIn("disabled", inspector.widgets["xscale"].state())
        self.assertNotIn("disabled", inspector.widgets["ymin"].state())
        self.assertIn("X axis, 3 segments", inspector.axis_breaks_label.cget("text"))
        self.assertEqual(committed, [])
        self.assertTrue(inspector.apply())
        self.assertEqual(committed[-1][AXIS_BREAKS]["axis"], "x")
        inspector.discard()
        self.assertEqual(len(segment_axes(figure)), 0)

    def test_cancelling_the_editor_leaves_the_draft_and_the_graph_alone(self):
        self.language("en")
        figure, inspector, committed = self.inspector(confirmed={AXIS_BREAKS: X_BREAKS})
        self.assertEqual(len(segment_axes(figure)), 3)
        errors = []

        def cancel(editor):
            editor.axis.set("y")
            self.assertTrue(editor.preview())
            self.assertEqual(ab.panel_scope(segment_axes(figure)[0])[0], "y")
            editor.cancel()

        self.modal(inspector, AxisBreaksDialog, cancel, errors)
        inspector._edit_axis_breaks()
        self.assertEqual(errors, [])
        self.assertEqual(inspector.draft[AXIS_BREAKS], X_BREAKS)
        self.assertEqual(ab.panel_scope(segment_axes(figure)[0])[0], "x")
        self.assertFalse(inspector.has_draft)

    def test_resetting_the_axes_section_removes_the_breaks(self):
        self.language("en")
        figure, inspector, committed = self.inspector(confirmed={AXIS_BREAKS: Y_BREAKS})
        self.assertIn("disabled", inspector.widgets["yscale"].state())
        inspector.reset_section("axes")
        self.assertNotIn(AXIS_BREAKS, inspector.draft)
        self.assertEqual(segment_axes(figure), [])
        self.assertEqual(inspector.axis_breaks_label.cget("text"), tr("axis_breaks.summary_none"))

    def test_saved_breaks_that_cannot_be_drawn_show_their_reason(self):
        self.language("it")
        figure, inspector, committed = self.inspector(RIGHT, {AXIS_BREAKS: X_BREAKS})
        self.assertEqual(segment_axes(figure), [])
        text = inspector.axis_breaks_label.cget("text")
        self.assertIn("salvate ma non disegnate", text)
        self.assertIn("asse Y destro", text)
        self.assertTrue(inspector.apply())
        self.assertEqual(committed[-1][AXIS_BREAKS], X_BREAKS)

    def test_the_busy_state_disables_the_button(self):
        self.language("en")
        figure, inspector, committed = self.inspector()
        inspector.set_busy("Calculating…")
        self.assertIn("disabled", inspector.axis_breaks_button.state())
        inspector.set_busy(None)
        self.assertNotIn("disabled", inspector.axis_breaks_button.state())

    def test_the_button_is_missing_where_breaks_do_not_apply(self):
        self.language("en")
        from tkinter import ttk
        from analisi.category_graphs import category_graph

        figure = category_graph(pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]}), {"Variables": ["A", "B"]}).figure
        apply_style(figure, {})
        run = SimpleNamespace(method="Column graph", style={}, result=SimpleNamespace(figure=figure, style_warning=None))
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        inspector = GraphInspector(holder, run, FigureCanvasTkAgg(figure, master=holder), None, confirmed=lambda: {},
                                   commit=lambda style: None, closed=lambda: None)
        self.addCleanup(inspector.dispose)
        self.assertNotIn("axis_breaks", inspector.widgets)


if __name__ == "__main__":
    unittest.main()
