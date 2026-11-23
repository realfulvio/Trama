"""Visual system and shell of the 0.70 interface: theme tokens, icons, ribbon density, grid drawing, dialogs.

The widget tests need Tk and a display (Xvfb is enough); they are skipped without one.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

import pandas as pd

import tramastat
from analisi import ui_icons, ui_shell, ui_theme


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first, second):
    a, b = sorted((luminance(first), luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


class ThemeTokenTests(unittest.TestCase):
    def test_text_contrast_meets_wcag_aa(self):
        for foreground, background in ((ui_theme.TEXT, ui_theme.CHROME), (ui_theme.TEXT, "#ffffff"),
                                       (ui_theme.MUTED, ui_theme.CHROME), (ui_theme.MUTED, "#ffffff"),
                                       ("#ffffff", ui_theme.ACCENT), (ui_theme.TEXT, ui_theme.SELECTED_CELL),
                                       (ui_theme.ERROR, ui_theme.ERROR_TINT),
                                       (ui_theme.EXCLUDED, "#ffffff")):
            self.assertGreaterEqual(contrast(foreground, background), 4.5, (foreground, background))

    def test_selection_is_visible_against_the_sheet(self):
        self.assertGreaterEqual(contrast(ui_theme.ACTIVE_CELL, "#ffffff"), 7)
        self.assertGreater(contrast(ui_theme.SELECTED_HEADING, "#ffffff"), 1.3)
        self.assertNotEqual(ui_theme.SELECTED_CELL, ui_theme.BLANK)

    def test_scale_helpers_follow_the_display_factor(self):
        saved = dict(ui_theme._state)
        try:
            for factor, size in ((1.0, 16), (1.25, 20), (1.5, 24), (2.0, 32)):
                ui_theme._state["scale"] = factor
                self.assertEqual(ui_theme.icon_size(), size)
                self.assertEqual(ui_theme.px(100), round(100 * factor))
            ui_theme._state["scale"] = 0.1
            self.assertEqual(ui_theme.px(3), 1)
        finally:
            ui_theme._state.update(saved)


class IconTests(unittest.TestCase):
    def test_every_icon_renders_at_every_size(self):
        for name in ui_icons.ICONS:
            for size in (16, 20, 24, 32):
                image = ui_icons.render(name, size, ink="#3a4e5a", accent="#0a7c76")
                self.assertEqual(image.size, (size, size), name)
                self.assertIsNotNone(image.getchannel("A").getbbox(), f"{name} is blank at {size}")

    def test_workspace_aliases_resolve_to_drawn_icons(self):
        from analisi.workspace_icons import ALIASES
        for alias, target in ALIASES.items():
            self.assertIn(target, ui_icons.ICONS, alias)


class TkCase(unittest.TestCase):
    theme = None

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Tk is not available: {error}")
        cls.root.geometry("1440x900+0+0")
        if cls.theme is None:
            cls.app = tramastat.App(cls.root)
        else:
            with patch.object(tramastat, "load_theme", return_value=cls.theme):
                cls.app = tramastat.App(cls.root)
        cls.errors = []
        cls.app.error = lambda error: cls.errors.append(str(error))
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.errors.clear()


class CalculationStatusTests(TkCase):
    def test_the_application_icon_belongs_to_its_own_root(self):
        second = tk.Tk()
        try:
            app = tramastat.App(second)
            try:
                self.assertIs(app.icon.tk, second.tk)
                self.assertEqual(second.tk.call("image", "type", str(app.icon)), "photo")
            finally:
                app.worker.shutdown(wait=True)
        finally:
            second.destroy()

    def test_long_status_keeps_the_cancel_button_visible_in_a_narrow_window(self):
        geometry = self.root.geometry()
        self.root.geometry("900x620+0+0")
        self.app._add_tables({"Measurements": pd.DataFrame({"Value": [1, 2]})})
        previous = self.app.status.get()
        try:
            self.app.begin_calculation(tramastat.CalculationControl())
            self.app.status.set("Bootstrap progress " * 80)
            self.root.update()
            button = self.app.cancel_button
            self.assertTrue(button.winfo_viewable())
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
            button.invoke()
            self.assertTrue(self.app.calculation.cancel.is_set())
        finally:
            self.app.end_calculation()
            self.app.status.set(previous)
            self.root.geometry(geometry)


class RibbonTests(TkCase):
    theme = "standard"

    def ribbon(self):
        return self.app.ribbon

    def test_density_grows_with_width_and_never_overflows(self):
        ribbon = self.ribbon()
        previous = -1
        for width in (max(820, ribbon.minimum_width()), 1024, 1280, 1440, 1920):
            ribbon.fit(width)
            self.assertLessEqual(ribbon.winfo_reqwidth(), width, f"ribbon overflows at {width}")
            self.assertGreaterEqual(ribbon.density, previous)
            previous = ribbon.density
        ribbon.fit(self.root.winfo_width())

    def test_narrow_buttons_keep_their_label_text_for_lookup(self):
        ribbon = self.ribbon()
        ribbon.set_density(0)
        for label, button in ribbon.buttons.items():
            self.assertTrue(button.cget("text"), label)
        ribbon.fit(self.root.winfo_width())

    def test_lead_buttons_stay_stacked_and_primary_is_styled(self):
        ribbon = self.ribbon()
        for density in (0, ui_shell.MAX_DENSITY):
            ribbon.set_density(density)
            self.assertEqual(str(ribbon.buttons["Paste"].cget("compound")), "top")
        self.assertIn("Primary", str(ribbon.buttons["Analyze…"].cget("style")))
        ribbon.fit(self.root.winfo_width())

    def test_every_command_of_the_old_ribbon_is_still_there(self):
        expected = {"New", "Open", "Save", "Cut cells", "Copy", "Paste", "Paste Special…", "Analyze…", "Import…"}
        self.assertTrue(expected <= set(self.ribbon().buttons))

    def test_formula_has_one_ribbon_button_and_is_reachable_in_the_menu(self):
        self.assertIn("Formula…", self.ribbon().buttons)
        self.assertNotIn("Add formula…", self.ribbon().buttons)
        self.assertIn(("Insert", "Calculated column…"), self.app.menu_entries)


class GridDrawingTests(TkCase):
    def setUp(self):
        super().setUp()
        frame = pd.DataFrame({"X": [1., 2., 3., 4.], "Y": [5., 6., 7., 8.]})
        self.app._add_tables({"Bench": frame})
        self.root.update()
        self.grid = self.app.current_grid

    def tearDown(self):
        self.root.update()

    def test_empty_covariance_result_keeps_its_row_heading(self):
        axes = pd.MultiIndex.from_arrays([[], [], []], names=["Scope", "Group", "Parameter"])
        frame = pd.DataFrame(index=axes, columns=axes)
        grid = tramastat.Grid(self.root, frame)
        self.addCleanup(grid.destroy)
        self.assertEqual(grid.cells.frame.shape, (0, 1))
        self.assertEqual(grid.cells.frame.columns.tolist(), ["Row"])

    def test_exclusion_and_export_have_distinct_shortcuts(self):
        table = self.app.tables[self.app.selected[1]]
        self.grid.select_block(0, 0, 0, 0)
        self.root.focus_force()
        self.grid.canvas.focus_set()
        self.root.update()

        with TemporaryDirectory() as folder:
            path = Path(folder) / "shortcut.csv"
            with patch.object(tramastat.filedialog, "asksaveasfilename", return_value=str(path)) as chooser:
                self.grid.canvas.event_generate("<Control-e>")
                self.root.update()
                self.assertEqual(table.excluded, {(0, 0)})
                chooser.assert_not_called()
                self.app.current_grid.canvas.event_generate("<Control-e>")
                self.root.update()
                self.assertFalse(table.excluded)
                self.app.current_grid.canvas.event_generate("<Control-Shift-E>")
                self.root.update()
                chooser.assert_called_once()
            pd.testing.assert_frame_equal(pd.read_csv(path), table.raw, check_dtype=False)

    def test_selection_and_active_cell_are_drawn_over_the_cells(self):
        self.grid.select_block(0, 0, 2, 1)
        self.grid.draw()
        colors = {self.grid.canvas.itemcget(item, "outline") for item in self.grid.canvas.find_all()
                  if self.grid.canvas.type(item) == "rectangle"}
        self.assertIn(ui_theme.ACTIVE_CELL, colors)

    def test_excluded_cell_gets_a_mark_and_italics_not_only_a_colour(self):
        self.grid.excluded.add((1, 1))
        self.grid.draw()
        polygons = [item for item in self.grid.canvas.find_all() if self.grid.canvas.type(item) == "polygon"]
        self.assertTrue(polygons, "no corner mark for the excluded cell")
        self.assertEqual(self.grid.excluded_font.actual("slant"), "italic")
        self.grid.excluded.discard((1, 1))

    def test_mouse_motion_does_not_redraw_the_grid(self):
        # The first pointer events after the table opens let Tk finish its pending scroll commands.
        self.grid.canvas.event_generate("<Motion>", x=80, y=70)
        for _ in range(3):
            self.root.update()
        calls = []
        original = self.grid.draw
        self.grid.draw = lambda *args, **kwargs: calls.append(1) or original(*args, **kwargs)
        try:
            for x in range(60, 200, 20):
                self.grid.canvas.event_generate("<Motion>", x=x, y=70)
            self.root.update()
        finally:
            self.grid.draw = original
        self.assertEqual(calls, [])

    def test_group_stripes_follow_the_series_colours(self):
        self.assertEqual(self.grid.series_color("Group A"), ui_theme.SERIES[0])
        self.assertEqual(self.grid.series_color("Group B"), ui_theme.SERIES[1])
        self.assertIsNone(self.grid.series_color("X"))
        self.assertIsNone(self.grid.series_color("Group"))


class ImportedPageExportTests(TkCase):
    def test_leaving_a_figure_page_releases_tk_images_without_discarding_the_result(self):
        import gc
        from weakref import ref

        from matplotlib.figure import Figure

        self.app._clear("Graph")
        self.root.update()
        gc.collect()
        before = set(self.root.tk.call("image", "names"))
        figure = Figure(figsize=(4, 3))
        axes = figure.add_subplot()
        axes.plot([0, 1], [1, 2])
        original_canvas = figure.canvas
        self.app.show_figure(figure)
        self.root.update()
        view = ref(figure.canvas)
        images = set(self.root.tk.call("image", "names")) - before
        self.assertTrue(images)

        figure.canvas.draw_idle()
        self.app._clear("Data")
        self.root.update()
        gc.collect()

        self.assertIs(figure.canvas, original_canvas)
        self.assertIsNone(view())
        self.assertFalse(images.intersection(self.root.tk.call("image", "names")))
        self.assertEqual(list(axes.lines[0].get_ydata()), [1, 2])

    def test_export_uses_saved_paper_after_the_canvas_resizes(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from matplotlib.figure import Figure
        from analisi.legacy_restore import SAVED_BINARY_LAYOUT
        from analisi.legacy_zip_layout import ZIP_LAYOUT
        from analisi.workbench import Result

        paper = (8.5, 11.)
        figure = Figure(figsize=paper)
        figure.add_subplot().plot([0, 1], [1, 2])
        self.app._add_tables({"Imported layout": pd.DataFrame({"Panels": [1]})})
        self.app.runs = [tramastat.Run(SAVED_BINARY_LAYOUT, "Imported layout",
                                       {ZIP_LAYOUT: {"paper": list(paper)}}, Result({}, figure))]
        self.app.show("saved-layout", 0)
        self.root.update()
        preview = tuple(figure.get_size_inches())
        self.assertNotEqual(preview, paper)
        toolbar = next(child for child in self.app.page.winfo_children()
                       if isinstance(child, tramastat.ImportedPageToolbar))
        with TemporaryDirectory() as folder:
            for name, export in (("menu", self.app.export), ("toolbar", toolbar.save_figure)):
                path = Path(folder) / f"{name}.svg"
                with patch("tramastat.filedialog.asksaveasfilename", return_value=str(path)):
                    export()
                svg = path.read_text(encoding="utf-8")
                self.assertIn('width="612pt" height="792pt"', svg)
                self.assertNotIn("<image ", svg)
                self.assertEqual(tuple(figure.get_size_inches()), preview)
        self.assertEqual(self.errors, [])


class DialogTests(TkCase):
    def test_calculated_column_menu_keeps_values_and_supports_undo(self):
        import tkinter as tk
        from analisi.i18n import tr

        self.app._add_tables({"Study": pd.DataFrame({"Dose": [2, 4], "Result": [None, None]})})
        data = self.app.tables["Study"]
        data.set_worksheet_formula(1, "=Dose * 2")
        self.app.show("data", "Study")
        self.root.update()
        grid = self.app.current_grid
        with patch.object(tk.Menu, "tk_popup", autospec=True) as popup:
            grid.canvas.event_generate("<Button-3>", x=int(grid.edges[0]) + 3, y=4)
            popup.assert_not_called()
            grid.canvas.event_generate("<Button-3>", x=int(grid.edges[1]) + 3, y=4)
            popup.assert_called_once()
        menu = popup.call_args.args[0]
        self.assertEqual(menu.entrycget(0, "label"), tr("worksheet.formula.freeze"))
        menu.invoke(0)
        self.assertEqual(data.formulas, {})
        self.assertEqual(data.raw["Result"].tolist(), [4, 8])
        self.app.apply_worksheet_history()
        self.assertIn("Result", data.formulas)
        self.app.apply_worksheet_history(redo=True)
        self.assertEqual(data.raw["Result"].tolist(), [4, 8])
        self.assertEqual(self.errors, [])

    def test_formula_reference_search_replaces_the_selection_and_preserves_a_quoted_name(self):
        from analisi.data import Dataset
        from analisi.graph_language_smoke import drive_mapped_dialog
        from analisi.worksheet_formula_dialog import WorksheetFormulaDialog

        name = "Nùmero [μM] 'étape'"
        data = Dataset(pd.DataFrame({**{f"Raw {index:02d}": [2., 4.] for index in range(26)}, name: [0., 1.]}))

        def enter(dialog):
            try:
                dialog.reference_group.current(1)
                dialog.reference_query.set("normpdf")
                self.assertIn("NORMPDF(x, mean, sd)", dialog.reference_detail.cget("text"))
                dialog.expression.insert(0, "=unused")
                dialog.expression.selection_range(1, "end")
                dialog.reference_insert.invoke()
                self.assertEqual(dialog.expression.get(), "=NORMPDF()")
                self.assertEqual(dialog.expression.index("insert"), len("=NORMPDF("))
                dialog.reference_group.current(0)
                dialog.reference_query.set("aa")
                self.assertEqual(dialog.reference_results.get(0), f"AA · {name}")
                dialog.reference_search.focus_force()
                dialog.update()
                dialog.reference_search.event_generate("<Return>")
                self.assertIsNone(dialog.result)
                self.assertTrue(dialog.winfo_exists())
                self.assertIn(repr(name), dialog.expression.get())
                dialog.ok()
                self.assertIsNotNone(dialog.result, dialog.problem.cget("text") if dialog.winfo_exists() else "")
            except Exception as error:
                self.errors.append(str(error))
                if dialog.winfo_exists():
                    dialog.cancel()

        drive_mapped_dialog(self.root, WorksheetFormulaDialog, enter, self.errors)
        dialog = WorksheetFormulaDialog(self.root, data, name="Density")
        self.assertFalse(self.errors, self.errors)
        self.assertIn(repr(name), dialog.result)
        data.set_formula("Density", dialog.result)
        self.assertAlmostEqual(data.frame()["Density"].iloc[0], 0.3989422804014327)

    def test_analysis_dialog_fits_the_screen_and_shows_the_error_banner(self):
        data = pd.DataFrame({"X": [1., 2., 3.], "Y": [2., 4., 6.]})
        shown = {}

        # Build the dialog through the real constructor but close it from the event loop.
        def close_when_open():
            window = next((w for w in self.root.winfo_children() if isinstance(w, tramastat.AnalysisDialog)), None)
            if window is None:
                self.root.after(50, close_when_open)
                return
            self.root.update()
            shown["height"] = window.fields.winfo_height()
            shown["buttons"] = window.winfo_rooty() + window.winfo_height() <= self.root.winfo_screenheight()
            shown["banner"] = window.error_label is not None and window.error_label.cget("text")
            window.cancel()

        self.root.after(100, close_when_open)
        tramastat.AnalysisDialog(self.root, data, current=("Linear regression", {"X": "X", "Y": "Y"}),
                                 error="Confidence level (%) must be finite and strictly between 0 and 100.")
        self.assertTrue(shown["buttons"])
        self.assertIn("Confidence level", shown["banner"])
        self.assertLessEqual(shown["height"], self.root.winfo_screenheight())


if __name__ == "__main__":
    unittest.main()
