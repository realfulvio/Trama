"""Tk dialog and Inspector tests for Q–Q panel formatting: drafts, preview, reset, cancel, EN/IT."""
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import traceback
import unittest

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd

from analisi import i18n, ui_theme
from analisi.graph_dialog import GraphFormatDialog
from analisi.graph_inspector import GraphInspector
from analisi.normality import NORMALITY, QQ_LINE, QQ_PLOT, QQ_VARIABLE
from analisi.presentation import apply_style
from analisi.qq_panel_dialog import QQPanelsDialog
from analisi.qq_panels import PANEL_KEY, panel_axes
from analisi.workbench import analyse
from tests.test_graph_i18n import TkCase


class QQPanelsDialogTests(TkCase):
    def setUp(self):
        ui_theme.configure(self.root)
        self.frame = pd.DataFrame({
            "A": [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0],
            "B": [2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 13.0, 20.0],
        })

    def make_result(self, mode="Both", *, show_line=True):
        return analyse(
            NORMALITY,
            self.frame,
            {"Variables": ["A"], "Distribution": mode, QQ_PLOT: True, QQ_VARIABLE: "A", QQ_LINE: show_line},
        )

    def drive_qq(self, figure, style, action, *, initial_panel=None, screen="1024x768+0+0"):
        holder_frame = ttk.Frame(self.root)
        holder_frame.pack(fill="both", expand=True)
        self.addCleanup(holder_frame.destroy)
        canvas = FigureCanvasTkAgg(figure, master=holder_frame)
        canvas.draw()
        seen, holder = {}, []

        def step():
            try:
                dialog = next(w for w in self.root.winfo_children() if isinstance(w, QQPanelsDialog))
                if dialog.grab_current() is not dialog:
                    self.root.after(10, step)
                    return
                holder.append(dialog)
                dialog.update_idletasks()
                action(dialog, canvas, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                for dialog in holder:
                    if dialog.winfo_exists():
                        dialog.cancel()

        self.root.deiconify()
        self.root.geometry(screen)
        self.root.update()
        self.root.after(60, step)
        dialog = QQPanelsDialog(self.root, figure, canvas, style, initial_panel=initial_panel)
        seen["result"] = dialog.result
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    def test_draft_switching_preview_reset_validation_and_cancel(self):
        res = self.make_result("Both")
        panels = panel_axes(res.figure)
        left, right = panels["normal"], panels["lognormal"]
        orig_left_title = left.get_title()
        orig_right_title = right.get_title()
        orig_right_xlim = right.get_xlim()
        confirmed = {"title": "Global Left"}
        apply_style(res.figure, confirmed)

        def action(dialog, canvas, seen):
            # Both panels reachable and buttons fit inside 1024x768.
            dialog.update()
            for btn in dialog.buttons.values():
                self.assertTrue(btn.winfo_viewable())
                self.assertLessEqual(btn.winfo_rooty() + btn.winfo_height(), 768)

            # Edit normal draft, switch to lognormal, edit lognormal, switch back: drafts preserved!
            dialog.vars["title"].set("Draft Left $a$")
            dialog.panel_binding.display.set("Lognormal Q–Q (lognormal)")
            dialog.update()
            self.assertEqual(dialog.current_panel, "lognormal")
            dialog.vars["title"].set("Right Valid {B}")
            dialog.vars["xmin"].set("-2,5")
            dialog.vars["xmax"].set("2,5")
            dialog.vars["legend_visible"].set(False)
            self.assertTrue(dialog.preview())
            seen["preview_right"] = (right.get_title(), tuple(right.get_xlim()), right.get_legend().get_visible())
            seen["preview_left"] = left.get_title()

            # Switch back to normal and verify draft text is still there.
            dialog.panel_binding.display.set("Normal Q–Q (normal)")
            dialog.update()
            seen["kept_left_draft"] = dialog.vars["title"].get()

            # Invalid single limit or min>=max on lognormal keeps last valid preview intact and focuses field.
            dialog.panel_binding.display.set("Lognormal Q–Q (lognormal)")
            dialog.update()
            for bad_min, bad_max, expected_sub in (("-1", "", "both"), ("3", "1", "smaller"), ("nan", "2", "finite")):
                dialog.vars["xmin"].set(bad_min)
                dialog.vars["xmax"].set(bad_max)
                self.assertFalse(dialog.preview())
                self.assertIn(expected_sub, dialog.error_labels["xrange"].cget("text").casefold())
                self.assertEqual(right.get_title(), "Right Valid {B}")
                self.assertEqual(tuple(right.get_xlim()), (-2.5, 2.5))
                self.assertIs(dialog.focus_get(), dialog.widgets["xmax" if bad_max == "" else "xmin"])

            # Over-long title rejected on field.
            dialog.vars["xmin"].set("-2,5")
            dialog.vars["xmax"].set("2,5")
            dialog.vars["title"].set("x" * 161)
            self.assertFalse(dialog.preview())
            self.assertIn("160", dialog.error_labels["title"].cget("text"))
            self.assertIs(dialog.focus_get(), dialog.widgets["title"])

            # Fix title, preview, then reset ONLY lognormal: left draft stays, right reverts to defaults.
            dialog.vars["title"].set("Right Valid {B}")
            self.assertTrue(dialog.preview())
            dialog.reset_selected()
            seen["after_reset_right"] = (
                right.get_title(),
                tuple(right.get_xlim()),
                right.get_legend().get_visible(),
                left.get_title(),
            )
            # Cancel restores confirmed style (Global Left + untouched default Right).
            dialog.cancel()

        seen = self.drive_qq(res.figure, confirmed, action)
        self.assertIsNone(seen["result"])
        self.assertEqual(seen["preview_right"], ("Right Valid {B}", (-2.5, 2.5), False))
        self.assertEqual(seen["preview_left"], "Draft Left $a$")
        self.assertEqual(seen["kept_left_draft"], "Draft Left $a$")
        self.assertEqual(seen["after_reset_right"], (orig_right_title, orig_right_xlim, True, "Draft Left $a$"))
        self.assertEqual(left.get_title(), "Global Left")
        self.assertEqual(right.get_title(), orig_right_title)
        self.assertNotEqual(orig_left_title, "Global Left")

    def test_italian_labels_choices_errors_and_apply_commit(self):
        self.use("it")
        res = self.make_result("Lognormal", show_line=False)
        panels = panel_axes(res.figure)
        self.assertEqual(list(panels), ["lognormal"])

        def action(dialog, canvas, seen):
            seen["choices"] = list(dialog.panel_box.cget("values"))
            seen["buttons"] = [dialog.buttons[k].cget("text") for k in ("preview", "reset", "cancel", "apply")]
            dialog.vars["xmin"].set("1")
            self.assertFalse(dialog.validate())
            seen["it_err"] = dialog.error_labels["xrange"].cget("text")
            dialog.vars["xmin"].set("-2,5")
            dialog.vars["xmax"].set("2,5")
            dialog.vars["title"].set("Titolo {log} $x$")
            dialog.vars["legend_visible"].set(True)
            dialog.ok()

        seen = self.drive_qq(res.figure, {}, action, screen="1600x1000+0+0")
        self.assertEqual(seen["choices"], ["Q–Q lognormale (lognormal)"])
        self.assertEqual(seen["buttons"], ["Anteprima", "Ripristina selezionato", "Annulla", "Applica"])
        self.assertIn("entrambi", seen["it_err"])
        self.assertEqual(
            seen["result"],
            {
                PANEL_KEY: {
                    "lognormal": {
                        "title": "Titolo {log} $x$",
                        "axis": {"x": {"min": -2.5, "max": 2.5}},
                        "legend_visible": True,
                    }
                }
            },
        )
        leg = panels["lognormal"].get_legend()
        self.assertIsNotNone(leg)
        self.assertTrue(leg.get_visible())

    def test_inspector_shows_button_only_on_qq_and_format_graph_preserves_qq_panels(self):
        # Non-Q-Q graph: button absent.
        lin = analyse("Linear regression", self.frame, {"X": "A", "Y": "B"})
        holder = ttk.Frame(self.root)
        holder.pack()
        self.addCleanup(holder.destroy)
        lin_canvas = FigureCanvasTkAgg(lin.figure, master=holder)
        lin_run = SimpleNamespace(style=None, result=SimpleNamespace(style_warning=None))
        lin_inspector = GraphInspector(
            holder, lin_run, lin_canvas, None, confirmed=lambda: lin_run.style,
            commit=lambda _s: None, closed=lambda: None, qq_panels=None,
        )
        self.addCleanup(lin_inspector.dispose)
        self.assertNotIn("qq_panels", lin_inspector.widgets)

        # Q-Q graph: Inspector shows button, and GraphFormatDialog preserves qq_panels.
        qq = self.make_result("Both")
        qq_canvas = FigureCanvasTkAgg(qq.figure, master=holder)
        qq_style = {PANEL_KEY: {"lognormal": {"title": "Right Saved"}}}
        qq_run = SimpleNamespace(style=qq_style, result=SimpleNamespace(style_warning=None))
        called = []
        qq_inspector = GraphInspector(
            holder, qq_run, qq_canvas, None, confirmed=lambda: qq_run.style,
            commit=lambda _s: None, closed=lambda: None, qq_panels=lambda: called.append(True),
        )
        self.addCleanup(qq_inspector.dispose)
        self.assertIn("qq_panels", qq_inspector.widgets)
        qq_inspector.widgets["qq_panels"].invoke()
        self.assertEqual(called, [True])

        seen = {}

        def drive_fmt():
            dlg = next(w for w in self.root.winfo_children() if isinstance(w, GraphFormatDialog))
            dlg.inputs["title"].set("Left Formatted")
            dlg.ok()
            seen["style"] = dlg.result

        self.root.after(60, drive_fmt)
        GraphFormatDialog(self.root, qq.figure.axes[0], qq_style)
        self.assertEqual(seen["style"]["title"], "Left Formatted")
        self.assertEqual(seen["style"][PANEL_KEY], {"lognormal": {"title": "Right Saved"}})

    def test_app_edit_qq_panels_settles_inspector_draft_and_commits(self):
        from unittest.mock import patch
        import tramastat

        self.root.deiconify()
        app = tramastat.App(self.root)
        app.error = lambda err: self.fail(str(err))

        def cleanup():
            self.root.update_idletasks()
            app.worker.shutdown(wait=True)
            for child in list(self.root.winfo_children()):
                child.destroy()
            self.root.withdraw()

        self.addCleanup(cleanup)

        opts = {"Variables": ["A"], "Distribution": "Both", QQ_PLOT: True, QQ_VARIABLE: "A", QQ_LINE: True}
        app._add_tables({"QQ": self.frame.copy()})
        app.tables["QQ"].analyses = [(NORMALITY, opts)]
        run = tramastat.Run(NORMALITY, "QQ", opts, result=analyse(NORMALITY, self.frame, opts), slot=0, style={})
        app.runs = [run]
        app.show("graph", 0)
        self.root.update()
        app.toggle_inspector()
        self.root.update()
        self.assertIsNotNone(app.inspector)
        self.assertIn("qq_panels", app.inspector.widgets)

        # Create an unapplied draft in the Inspector.
        app.inspector.vars["title"].set("Draft Inspector Title")
        app.inspector._update("title")
        self.assertTrue(app.inspector.has_draft)

        # 1) Cancel prompt keeps draft and does not open QQPanelsDialog.
        with patch.object(tramastat.messagebox, "askyesnocancel", return_value=None) as ask:
            app.edit_qq_panels()
            self.assertEqual(ask.call_count, 1)
        self.assertTrue(app.inspector.has_draft)
        self.assertFalse(run.style)

        # 2) Discard ("No" -> False) discards Inspector draft and commits QQPanelsDialog edit.
        def drive_log_title(title_text):
            def step():
                dlg = next((w for w in self.root.winfo_children() if isinstance(w, QQPanelsDialog)), None)
                if dlg is None or dlg.grab_current() is not dlg:
                    self.root.after(10, step)
                    return
                dlg.panel_binding.display.set("Lognormal Q–Q (lognormal)")
                dlg.update()
                dlg.vars["title"].set(title_text)
                dlg.ok()

            self.root.after(40, step)

        with patch.object(tramastat.messagebox, "askyesnocancel", return_value=False):
            drive_log_title("Right Discarded Draft")
            app.edit_qq_panels()
        self.assertNotIn("title", run.style)
        self.assertEqual(run.style[PANEL_KEY]["lognormal"]["title"], "Right Discarded Draft")

        # 3) Create another draft, choose Yes -> applies Inspector draft then edits QQ panel and preserves both.
        app.inspector.vars["title"].set("Accepted Left")
        app.inspector._update("title")
        self.assertTrue(app.inspector.has_draft)
        with patch.object(tramastat.messagebox, "askyesnocancel", return_value=True):
            drive_log_title("Right With Left")
            app.edit_qq_panels()
        self.assertEqual(run.style.get("title"), "Accepted Left")
        self.assertEqual(run.style[PANEL_KEY]["lognormal"]["title"], "Right With Left")
        self.assertEqual(app.inspector.draft.get("title"), "Accepted Left")
        self.assertEqual(app.inspector.draft[PANEL_KEY]["lognormal"]["title"], "Right With Left")

    def test_points_and_reference_tabs_en_it_errors_disable_and_unavailable_line(self):
        from tkinter import colorchooser
        from unittest.mock import patch
        from analisi.qq_panels import POINTS_KEY, REFERENCE_KEY

        res = self.make_result("Both", show_line=True)
        panels = panel_axes(res.figure)

        # Open in IT: verify ChoiceBinding labels, swatch/picker, decimal comma, dependency disable, errors, Apply.
        self.use("it")

        def action_it(dialog, canvas, seen):
            seen["tabs_it"] = [dialog.notebook.tab(i, "text") for i in range(3)]
            dialog.update()
            for btn in dialog.buttons.values():
                self.assertTrue(btn.winfo_viewable())
                self.assertLessEqual(btn.winfo_rooty() + btn.winfo_height(), 768)

            # Without touching anything, Apply returns empty/unmodified result (no spurious overrides).
            dialog.panel_binding.display.set("Q–Q lognormale (lognormal)")
            dialog.update()
            self.assertEqual(dialog.vars["points_marker"].get(), "")
            self.assertEqual(dialog.vars["points_size"].get(), "")

            # Switch to normal, edit points via Italian ChoiceBinding, decimal comma and picker.
            dialog.panel_binding.display.set("Q–Q normale (normal)")
            dialog.update()
            dialog.notebook.select(dialog.tabs["points"])
            dialog.marker_binding.display.set("Quadrato")
            dialog.vars["points_size"].set("7,0")
            dialog.vars["points_alpha"].set("0,65")
            with patch.object(colorchooser, "askcolor", return_value=((18, 122, 120), "#127A78")):
                dialog.pickers["points_color"].invoke()
            seen["swatch_pts"] = dialog.swatches["points_color"].cget("background")
            self.assertEqual(dialog.vars["points_color"].get(), "#127A78")

            # Disable points_visible -> disables dependent controls without clearing values, then re-enable.
            dialog.vars["points_visible"].set(False)
            dialog._sync_artist_controls()
            self.assertEqual(str(dialog.widgets["points_size"].cget("state")), "disabled")
            self.assertEqual(dialog.vars["points_size"].get(), "7,0")
            dialog.vars["points_visible"].set(True)
            dialog._sync_artist_controls()
            self.assertEqual(str(dialog.widgets["points_size"].cget("state")), "normal")

            # Invalid reference width -> auto-selects Reference line tab & focuses ref_width.
            dialog.notebook.select(dialog.tabs["axes"])
            dialog.vars["ref_width"].set("25")
            self.assertFalse(dialog.preview())
            self.assertEqual(dialog.notebook.select(), str(dialog.tabs["reference"]))
            self.assertIs(dialog.focus_get(), dialog.widgets["ref_width"])
            dialog.vars["ref_width"].set("2,0")
            dialog.ref_style_binding.display.set("tratteggiata")
            dialog.vars["ref_color"].set("#d1553a")
            dialog.vars["ref_alpha"].set("0,8")
            seen["swatch_ref"] = dialog.swatches["ref_color"].cget("background")
            self.assertTrue(dialog.preview())
            seen["preview_size"] = float(getattr(panels["normal"], "_trama_qq_points").get_sizes()[0])
            dialog.ok()

        seen = self.drive_qq(res.figure, {}, action_it)
        self.assertEqual(seen["tabs_it"], ["Assi e titolo", "Punti", "Retta di riferimento"])
        self.assertEqual(seen["swatch_pts"].lower(), "#127a78")
        self.assertEqual(seen["swatch_ref"].lower(), "#d1553a")
        self.assertAlmostEqual(seen["preview_size"], 49.0)
        self.assertEqual(
            seen["result"][PANEL_KEY]["normal"],
            {
                POINTS_KEY: {"marker": "s", "size": 7.0, "color": "#127A78", "alpha": 0.65},
                REFERENCE_KEY: {"color": "#d1553a", "width": 2.0, "style": "--", "alpha": 0.8},
            },
        )

        # Unavailable reference line (show_line=False): reference controls disabled + explanation shown,
        # existing saved reference_line preference preserved even across Reset+Cancel!
        no_line = self.make_result("Normal", show_line=False)
        saved_pref = {
            PANEL_KEY: {
                "normal": {
                    POINTS_KEY: {"marker": "D"},
                    REFERENCE_KEY: {"visible": True, "color": "#223344", "width": 2.0},
                }
            }
        }
        apply_style(no_line.figure, saved_pref)

        def action_no_line(dialog, canvas, seen):
            seen["unavail_msg"] = dialog.ref_unavailable_label.cget("text")
            seen["ref_state"] = str(dialog.widgets["ref_visible"].cget("state"))
            dialog.notebook.select(dialog.tabs["reference"])
            dialog.update()
            self.assertTrue(dialog.ref_unavailable_label.winfo_viewable())
            dialog.reset_selected()
            dialog.cancel()

        seen2 = self.drive_qq(no_line.figure, saved_pref, action_no_line, screen="1600x1000+0+0")
        self.assertIsNone(seen2["result"])
        self.assertEqual(seen2["ref_state"], "disabled")
        self.assertTrue(len(seen2["unavail_msg"]) > 10)
        # Re-open and Apply without changes -> preserved reference_line preference stays in style!
        def just_ok(dialog, canvas, seen):
            dialog.ok()

        seen3 = self.drive_qq(no_line.figure, saved_pref, just_ok)
        self.assertEqual(seen3["result"][PANEL_KEY]["normal"][REFERENCE_KEY], {"visible": True, "color": "#223344", "width": 2.0})

    def test_format_graph_reset_preserves_qq_panels_artist_styles(self):
        from analisi.qq_panels import POINTS_KEY, REFERENCE_KEY

        qq = self.make_result("Both")
        qq_style = {
            "title": "Global Title",
            PANEL_KEY: {
                "normal": {POINTS_KEY: {"marker": "^", "size": 6.0, "color": "#127A78"}},
                "lognormal": {REFERENCE_KEY: {"visible": False, "color": "#D1553A"}},
            },
        }
        seen = {}

        def drive_reset():
            dlg = next(w for w in self.root.winfo_children() if isinstance(w, GraphFormatDialog))
            dlg._reset()
            seen["reset_result"] = dlg.result

        self.root.after(60, drive_reset)
        GraphFormatDialog(self.root, qq.figure.axes[0], qq_style)
        self.assertNotIn("title", seen["reset_result"])
        self.assertEqual(seen["reset_result"][PANEL_KEY], qq_style[PANEL_KEY])


if __name__ == "__main__":
    unittest.main()
