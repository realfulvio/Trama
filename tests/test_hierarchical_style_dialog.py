"""Tk editor for hierarchical presentation: preview, cancel, Apply and disabled pages."""
import copy
import traceback
import unittest
from types import SimpleNamespace

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from analisi.graph_dialog import GraphFormatDialog
from analisi.graph_inspector import GraphInspector
from analisi.hierarchical_style import describe_hierarchical_artists
from analisi.hierarchical_style_dialog import HierarchicalStyleDialog
from analisi.hierarchical_workbench import hierarchical_result
from analisi.i18n import CATALOGS, placeholders, translate_message
from tests.test_graph_i18n import TkCase
from tests.test_hierarchical_style import _frame, _options


def _figure(**extra):
    return hierarchical_result(_frame(), _options(**extra)).figure


class HierarchicalStyleDialogTests(TkCase):
    def drive(self, figure, style, action, *, screen="1024x768+0+0"):
        seen, holder = {}, []

        def step():
            try:
                dialog = next(widget for widget in self.root.winfo_children()
                              if isinstance(widget, HierarchicalStyleDialog))
                if dialog.grab_current() is not dialog:
                    self.root.after(10, step)
                    return
                holder.append(dialog)
                dialog.update_idletasks()
                action(dialog, seen)
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
        dialog = HierarchicalStyleDialog(self.root, figure, None, style)
        seen["result"] = dialog.result
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    def test_catalog_has_both_languages_and_translates_engine_errors(self):
        english = [key for key in CATALOGS["en"] if key.startswith("hierarchy.style.")]
        self.assertGreater(len(english), 40)
        for key in english:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)
        self.use("it")
        text = translate_message("Enter a finite number.", "hierarchy.style.error.")
        self.assertEqual(text, "Inserisci un numero finito.")
        angle = translate_message("Enter a label angle from −90 to 90 degrees.", "hierarchy.style.error.")
        self.assertIn("−90", angle)
        self.assertNotEqual(angle, "Enter a label angle from −90 to 90 degrees.")

    def test_preview_accepts_a_decimal_comma_and_cancel_restores(self):
        figure = _figure()
        before = describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0]

        def action(dialog, seen):
            self.assertTrue(dialog.ok_button.winfo_ismapped())
            self.assertTrue(dialog.cancel_button.winfo_ismapped())
            self.assertTrue(dialog.preview_button.winfo_ismapped())
            self.assertLess(
                dialog.ok_button.winfo_rooty() + dialog.ok_button.winfo_height(),
                dialog.winfo_rooty() + dialog.winfo_height() + 2)
            dialog.vars["row.width"].set("3,5")
            self.assertTrue(dialog.preview())
            seen["preview"] = describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0]
            dialog.event_generate("<Escape>")

        seen = self.drive(figure, {"title": "Keep"}, action)
        self.assertAlmostEqual(seen["preview"], 3.5)
        self.assertIsNone(seen["result"])
        self.assertAlmostEqual(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0], before)

    def test_apply_keeps_other_style_keys_and_stores_only_the_difference(self):
        figure = _figure()

        def action(dialog, seen):
            dialog.vars["row.width"].set("4")
            dialog.ok()

        seen = self.drive(figure, {"title": "Keep", "legend_options": {"entries": []}}, action)
        result = seen["result"]
        self.assertEqual(result["title"], "Keep")
        self.assertEqual(result["legend_options"], {"entries": []})
        self.assertEqual(result["hierarchical"]["row"]["width"], 4)
        self.assertNotIn("color_mode", result["hierarchical"]["row"])
        self.assertAlmostEqual(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0], 4)

    def test_a_bad_field_is_focused_and_does_not_draft_the_figure(self):
        figure = _figure()
        before = describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0]
        self.use("it")

        def action(dialog, seen):
            dialog.vars["heatmap.minimum"].set("1")
            dialog.notebook.select(dialog.tabs["row"])
            self.assertFalse(dialog.preview())
            seen["focused"] = dialog.focus_get() is dialog.widgets["heatmap.maximum"]
            seen["on_heatmap"] = dialog.notebook.select() == str(dialog.tabs["heatmap"])
            seen["message"] = dialog.problem.cget("text")

        seen = self.drive(figure, {}, action)
        self.assertTrue(seen["focused"])
        self.assertTrue(seen["on_heatmap"])
        self.assertIn("automatici", seen["message"])
        self.assertAlmostEqual(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0], before)

    def test_missing_components_disable_their_pages(self):
        rows = _figure(**{"Direction": "Rows"})
        standalone = _figure(**{"Graph output": "Dendrogram", "Direction": "Columns",
                                "Dendrogram orientation": "Vertical"})

        def rows_action(dialog, seen):
            seen["column"] = dialog.notebook.tab(dialog.tabs["column"], "state")
            seen["layout"] = dialog.notebook.tab(dialog.tabs["layout"], "state")
            seen["ratio"] = str(dialog.widgets["layout.column_tree_ratio"].cget("state"))
            dialog.cancel()

        def tree_action(dialog, seen):
            seen["heat"] = dialog.notebook.tab(dialog.tabs["heatmap"], "state")
            seen["layout"] = dialog.notebook.tab(dialog.tabs["layout"], "state")
            seen["row"] = dialog.notebook.tab(dialog.tabs["row"], "state")
            dialog.cancel()

        rows_seen = self.drive(rows, {}, rows_action)
        self.assertEqual(rows_seen["column"], "disabled")
        self.assertEqual(rows_seen["layout"], "normal")
        self.assertEqual(rows_seen["ratio"], "disabled")
        tree_seen = self.drive(standalone, {}, tree_action)
        self.assertEqual(tree_seen["heat"], "disabled")
        self.assertEqual(tree_seen["layout"], "disabled")
        self.assertEqual(tree_seen["row"], "disabled")

    def test_italian_choices_stay_canonical(self):
        figure = _figure()
        self.use("it")

        def action(dialog, seen):
            seen["mode"] = dialog.vars["row.color_mode"].get()
            seen["shown"] = dialog.widgets["row.color_mode"].get()
            dialog.vars["row.color_mode"].set("cluster")
            seen["shown_after"] = dialog.widgets["row.color_mode"].get()
            dialog.cancel()

        seen = self.drive(figure, {}, action)
        self.assertEqual(seen["mode"], "analysis")
        self.assertEqual(seen["shown"], "Colori dell’analisi")
        self.assertEqual(seen["shown_after"], "Per cluster")

    def test_format_graph_keeps_hierarchical_and_legend_options(self):
        figure = _figure()
        style = {"title": "Keep", "hierarchical": {"row": {"width": 3}},
                 "legend_options": {"title": "Kept legend", "frame": False}}
        holder = []

        def step():
            try:
                dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, GraphFormatDialog))
                holder.append(dialog)
                dialog.update_idletasks()

                def captions(widget):
                    found = []
                    try:
                        found.append(widget.cget("text"))
                    except Exception:
                        pass
                    for child in widget.winfo_children():
                        found.extend(captions(child))
                    return found

                self.assertIn("Dendrograms and heat map…", captions(dialog))
                dialog.ok()
            except Exception:
                holder.append(traceback.format_exc())

        self.root.deiconify()
        self.root.geometry("1100x800+0+0")
        self.root.update()
        self.root.after(80, step)
        dialog = GraphFormatDialog(self.root, figure.axes[0], copy.deepcopy(style))
        if holder and isinstance(holder[0], str):
            self.fail(holder[0])
        self.assertEqual(dialog.result["title"], "Keep")
        self.assertEqual(dialog.result["hierarchical"]["row"]["width"], 3)
        self.assertEqual(dialog.result["legend_options"], {"title": "Kept legend", "frame": False})
        self.assertEqual(dialog.result["xlabel"], "")

    def test_inspector_button_follows_the_callback(self):
        figure = _figure()
        holder = self.root
        canvas = FigureCanvasTkAgg(figure, master=holder)
        canvas.draw()
        run = SimpleNamespace(method="Hierarchical clustering",
                              result=SimpleNamespace(figure=figure, style_warning=None), style={})
        plain = GraphInspector(holder, run, canvas, None, confirmed=lambda: {}, commit=lambda _style: None,
                               closed=lambda: None)
        self.addCleanup(plain.destroy)
        self.assertNotIn("hierarchical_style", plain.widgets)
        called = []
        panel = GraphInspector(holder, run, canvas, None, confirmed=lambda: {}, commit=lambda _style: None,
                               closed=lambda: None, hierarchical_style=lambda: called.append(True))
        self.addCleanup(panel.destroy)
        panel.update_idletasks()
        panel.widgets["hierarchical_style"].invoke()
        self.assertEqual(called, [True])

    def test_preview_on_a_copy_leaves_the_saved_figure_alone(self):
        import copy as copy_module

        figure = _figure()
        saved = describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0]
        clone = copy_module.deepcopy(figure)

        def action(dialog, seen):
            dialog.vars["row.width"].set("6")
            dialog.preview()
            seen["copy"] = describe_hierarchical_artists(clone)["row"]["branches"].get_linewidths()[0]
            seen["saved"] = describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0]
            dialog.cancel()

        seen = self.drive(clone, {}, action)
        self.assertAlmostEqual(seen["copy"], 6)
        self.assertAlmostEqual(seen["saved"], saved)
        self.assertAlmostEqual(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths()[0], saved)


if __name__ == "__main__":
    unittest.main()
