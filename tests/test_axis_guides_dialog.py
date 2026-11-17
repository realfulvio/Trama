"""Tk GUI and two-level transaction tests for AxisGuidesDialog, AxisBandsDialog, Format Graph, and Inspector."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd
from PIL import Image

from analisi.axis_guides import AXIS_BANDS, AXIS_GUIDES
from analisi.axis_guides_dialog import AxisBandsDialog, AxisGuidesDialog, BandEditorDialog, GuideEditorDialog
from analisi.category_graphs import category_graph
from analisi.graph_dialog import GraphFormatDialog
from analisi.graph_inspector import GraphInspector
from analisi.i18n import active_language, set_language, tr
from analisi.presentation import apply_style
from analisi.probability_scale import FRACTION_SCALE
from analisi.workbench import _preview_figure


def _find_child(parent, cls):
    for child in parent.winfo_children():
        if isinstance(child, cls):
            return child
        found = _find_child(child, cls)
        if found is not None:
            return found
    return None


class AxisGuidesGuiTests(unittest.TestCase):
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

    def use_lang(self, code):
        prev = active_language()
        set_language(code)
        self.addCleanup(set_language, prev)

    def _drive_modal(self, parent, cls, fn, errors):
        def step():
            dlg = _find_child(parent, cls)
            if dlg is None:
                errors.append(AssertionError(f"{cls.__name__} did not open"))
                return
            try:
                fn(dlg)
            except Exception as exc:
                errors.append(exc)
                if dlg.winfo_exists():
                    dlg.cancel()

        self.root.after(100, step)

    @staticmethod
    def make_xy_axes():
        fig = Figure(figsize=(5, 4), dpi=100)
        ax = fig.add_subplot()
        ax.plot([0.0, 1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 4.0, 2.0, 1.0], label="S1")
        ax.set_xlim(0.0, 4.0)
        ax.set_ylim(0.0, 5.0)
        return fig, ax

    def test_decimal_comma_literal_label_and_error_recovery_after_preview(self):
        self.use_lang("it")
        fig, ax = self.make_xy_axes()
        seen_previews = []
        errors = []

        def drive_list(dlg):
            self.assertEqual(dlg.title(), "Tacche e griglie aggiuntive")

            def drive_editor(ed):
                ed.fields["value"].set("2,5")
                ed.fields["tick"].set(True)
                ed.fields["line"].set(True)
                ed.fields["label"].set("Dose, A")
                ed.fields["width"].set("1,5")
                # Valid preview first
                self.assertTrue(ed.preview())
                self.assertEqual(len(seen_previews), 1)

                # Invalid width -> error on width field, dialog stays open, no partial preview
                ed.fields["width"].set("99")
                self.assertFalse(ed.preview())
                self.assertTrue(ed.winfo_exists())
                self.assertIs(ed.error_widget, ed.widgets["width"])
                self.assertTrue(ed.problem.cget("text"))

                # Fix width and accept without reopening
                ed.fields["width"].set("2,0")
                ed.ok()

            self._drive_modal(dlg, GuideEditorDialog, drive_editor, errors)
            dlg.add()
            if errors:
                dlg.cancel()
                return
            self.assertEqual(len(dlg.records), 1)
            self.assertEqual(dlg.records[0]["value"], 2.5)
            self.assertEqual(dlg.records[0]["width"], 2.0)
            self.assertEqual(dlg.records[0]["label"], "Dose, A")

            # Duplicate creates a distinct UUID and triggers tick collision on Apply, highlighting row 1
            dlg.tree.selection_set("0")
            dlg.duplicate()
            self.assertEqual(len(dlg.records), 2)
            self.assertNotEqual(dlg.records[0]["id"], dlg.records[1]["id"])
            self.assertFalse(dlg.validate())
            self.assertEqual(dlg.selected_index(), 1)
            self.assertTrue(dlg.message.cget("text"))

            # Remove the colliding duplicate and Apply
            dlg.remove()
            self.assertEqual(len(dlg.records), 1)
            dlg.ok()

        self._drive_modal(self.root, AxisGuidesDialog, drive_list, errors)
        dlg = AxisGuidesDialog(self.root, ax, [], preview=lambda recs: seen_previews.append(deepcopy(recs)))
        if errors:
            raise errors[0]
        self.assertIsNotNone(dlg.result)
        self.assertEqual(len(dlg.result), 1)
        self.assertEqual(dlg.result[0]["label"], "Dose, A")

    def test_two_level_cancel_in_inspector_and_busy_guard(self):
        self.use_lang("en")
        fig, ax = self.make_xy_axes()
        confirmed_style = {"title": "Confirmed"}
        run = SimpleNamespace(method="Linear regression", style=deepcopy(confirmed_style),
                              result=SimpleNamespace(figure=fig, style_warning=None))
        apply_style(fig, confirmed_style)
        committed = []
        from tkinter import ttk
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(fig, master=holder)
        inspector = GraphInspector(holder, run, canvas, None, confirmed=lambda: run.style,
                                   commit=committed.append, closed=lambda: None)
        self.addCleanup(inspector.dispose)

        # Parent Inspector edits draft title -> draft differs from confirmed
        inspector.vars["title"].set("Draft Title")
        inspector._now("title")
        self.assertEqual(ax.get_title(), "Draft Title")

        # Child AxisGuidesDialog previews a guide, then Cancels -> parent draft restored
        errors = []

        def drive_child_cancel(dlg):
            def drive_add(ed):
                ed.fields["value"].set("2.5")
                ed.fields["tick"].set(True)
                ed.fields["label"].set("Temp")
                self.assertTrue(ed.preview())
                self.assertIn("Temp", [t.get_text() for t in ax.get_xticklabels()])
                ed.ok()

            self._drive_modal(dlg, GuideEditorDialog, drive_add, errors)
            dlg.add()
            if errors:
                dlg.cancel()
                return
            dlg.preview()
            self.assertIn("Temp", [t.get_text() for t in ax.get_xticklabels()])
            dlg.cancel()

        self._drive_modal(inspector, AxisGuidesDialog, drive_child_cancel, errors)
        inspector._edit_axis_guides()
        if errors:
            raise errors[0]
        self.assertNotIn(AXIS_GUIDES, inspector.draft)
        self.assertEqual(ax.get_title(), "Draft Title")
        self.assertNotIn("Temp", [t.get_text() for t in ax.get_xticklabels()])

        # Now Child AxisBandsDialog applies a band into Inspector draft, then Inspector Cancel restores confirmed
        def drive_band_apply(dlg):
            def drive_add(ed):
                ed.fields["lower"].set("1.0")
                ed.fields["upper"].set("3.0")
                ed.fields["color"].set("#ccddee")
                ed.fields["alpha"].set("0.2")
                ed.ok()

            self._drive_modal(dlg, BandEditorDialog, drive_add, errors)
            dlg.add()
            if errors:
                dlg.cancel()
                return
            dlg.ok()

        self._drive_modal(inspector, AxisBandsDialog, drive_band_apply, errors)
        inspector._edit_axis_bands()
        if errors:
            raise errors[0]
        self.assertEqual(len(inspector.draft.get(AXIS_BANDS, [])), 1)
        self.assertEqual(committed, [])  # Inspector Apply not pressed yet!

        # Busy guard disables guide and band buttons
        inspector.set_busy("Calculating…")
        self.assertIn("disabled", inspector.axis_guides_button.state())
        self.assertIn("disabled", inspector.axis_bands_button.state())
        inspector.set_busy(None)
        self.assertNotIn("disabled", inspector.axis_guides_button.state())

        # Parent Inspector Cancel restores confirmed style without writing run.style
        inspector.discard()
        self.assertEqual(ax.get_title(), "Confirmed")
        self.assertFalse(any(str(a.get_gid()).startswith("trama-axis-band:") for a in ax.get_children()))
        self.assertEqual(committed, [])

    def test_format_graph_keeps_old_projects_clean_and_preserves_reference_lines(self):
        self.use_lang("en")
        _, ax = self.make_xy_axes()
        legacy_style = {"title": "Old", "reference_lines": [{"axis": "y", "value": 2.0, "label": "Ref"}]}
        errors = []

        def drive(dlg):
            self.assertEqual(dlg.guides_summary.cget("text"), tr("graph.guides.summary_none"))
            dlg.ok()

        self._drive_modal(self.root, GraphFormatDialog, drive, errors)
        dlg = GraphFormatDialog(self.root, ax, deepcopy(legacy_style))
        if errors:
            raise errors[0]
        self.assertEqual(dlg.result["reference_lines"], legacy_style["reference_lines"])
        self.assertNotIn(AXIS_GUIDES, dlg.result)
        self.assertNotIn(AXIS_BANDS, dlg.result)

    def test_unsupported_axes_explain_reason_without_losing_saved_styles(self):
        self.use_lang("en")
        errors = []

        # 1. Column graph: X categorical rejected on add, Y allowed
        col_df = pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]})
        col_res = category_graph(col_df, {"Variables": ["A", "B"]})
        col_ax = col_res.figure.axes[0]

        def drive_col(dlg):
            def drive_add(ed):
                ed.fields["axis"].set("x")  # Categorical X!
                ed.fields["value"].set("0.5")
                self.assertFalse(ed.validate())
                self.assertIn("categorical", ed.problem.cget("text").casefold())
                ed.fields["axis"].set("y")
                ed.fields["value"].set("2.5")
                ed.ok()

            self._drive_modal(dlg, GuideEditorDialog, drive_add, errors)
            dlg.add()
            if errors:
                dlg.cancel()
                return
            dlg.ok()

        self._drive_modal(self.root, AxisGuidesDialog, drive_col, errors)
        dlg = AxisGuidesDialog(self.root, col_ax, [])
        if errors:
            raise errors[0]
        self.assertEqual(len(dlg.result), 1)
        self.assertEqual(dlg.result[0]["axis"], "y")

        # 2. Non-native view disables Add and shows clear explanation
        preview_fig = _preview_figure(Image.new("RGB", (60, 60), "white"))

        def drive_non_native(dlg):
            self.assertIn("disabled", dlg.buttons["add"].state())
            dlg.cancel()

        self._drive_modal(self.root, AxisGuidesDialog, drive_non_native, errors)
        AxisGuidesDialog(self.root, preview_fig.axes[0], [])
        if errors:
            raise errors[0]

        # 3. Probability axis rejected in BandEditorDialog
        _, ax = self.make_xy_axes()
        ax.set_yscale(FRACTION_SCALE)

        def drive_prob(dlg):
            def drive_add(ed):
                ed.fields["axis"].set("y")
                ed.fields["lower"].set("0.1")
                ed.fields["upper"].set("0.9")
                self.assertFalse(ed.validate())
                self.assertTrue(ed.problem.cget("text"))
                ed.cancel()

            self._drive_modal(dlg, BandEditorDialog, drive_add, errors)
            dlg.add()
            dlg.cancel()

        self._drive_modal(self.root, AxisBandsDialog, drive_prob, errors)
        AxisBandsDialog(self.root, ax, [])
        if errors:
            raise errors[0]


if __name__ == "__main__":
    unittest.main()
