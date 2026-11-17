"""Visual system and shell of the 0.70 interface: theme tokens, icons, ribbon density, grid drawing, dialogs.

The widget tests need Tk and a display (Xvfb is enough); they are skipped without one.
"""
import tkinter as tk
import unittest

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
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Tk is not available: {error}")
        cls.root.geometry("1440x900+0+0")
        cls.app = tramastat.App(cls.root)
        cls.errors = []
        cls.app.error = lambda error: cls.errors.append(str(error))
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.errors.clear()


class RibbonTests(TkCase):
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


class GridDrawingTests(TkCase):
    def setUp(self):
        super().setUp()
        frame = pd.DataFrame({"X": [1., 2., 3., 4.], "Y": [5., 6., 7., 8.]})
        self.app._add_tables({"Bench": frame})
        self.root.update()
        self.grid = self.app.current_grid

    def tearDown(self):
        self.root.update()

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


class DialogTests(TkCase):
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
