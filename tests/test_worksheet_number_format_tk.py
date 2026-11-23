"""Change → Number format… in the classic Tk window: data grid, result tabs, copy, undo and the real dialog."""
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analisi.theme_preferences import save_theme
from analisi.worksheet_number_format import format_number
from tests.test_graph_i18n import TkCase

FIXTURE = pd.DataFrame({
    "Categoria": ["Controllo", "Prima", "Seconda", "Terza", "Quarta"],
    "Dose": [0.000125, 1.23456789012345, 12345.6789, 0.5, float("nan")],
    "Risposta": [2.125, -0.0004, -0.0, 1.2345e-14, 950.0],
    "Repliche": [4, 4, 12, 9999, 0],
})


class Chosen:
    """A stand-in for the modal dialog: remembers the target and returns ``choice``."""
    seen = []
    choice = None

    def __init__(self, parent, target):
        Chosen.seen.append(target)
        self.choice = Chosen.choice


class TkNumberFormatTests(TkCase):
    def setUp(self):
        import tramastat
        self.module = tramastat
        self.use("en")
        self.tmp = tempfile.TemporaryDirectory()
        prefs = Path(self.tmp.name) / "prefs.json"
        save_theme(prefs, "standard")
        self.root.deiconify()
        self.root.geometry("1024x768+0+0")
        with patch.object(tramastat, "config_path", return_value=prefs):
            self.app = tramastat.App(self.root)
        self.errors = []
        self.app.error = lambda error: self.errors.append(str(error))
        Chosen.seen = []
        self.root.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app._clear("")
            self.app.worker.shutdown(wait=True)
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.withdraw()
        self.tmp.cleanup()

    def format(self, choice):
        import analisi.worksheet_number_format_dialog as dialogs
        Chosen.choice = choice
        with patch.object(dialogs, "NumberFormatDialog", Chosen):
            self.app.change_number_format()
        self.root.update()

    def test_data_grid_shows_the_format_copies_the_numbers_and_undoes(self):
        app = self.app
        app._add_tables({"celle": FIXTURE.copy()})
        self.root.update()
        grid = app.current_grid
        grid.select_block(0, 0, 4, 2)
        self.format(("apply", {"mode": "scientific", "digits": 2}))
        target = Chosen.seen[0]
        self.assertEqual(target.changing_text(), "Columns that change: Dose, Risposta")
        self.assertIn("Categoria", target.unchanged_text())
        data = app.tables["celle"]
        self.assertEqual(data.number_formats, {"Dose": {"mode": "scientific", "digits": 2},
                                               "Risposta": {"mode": "scientific", "digits": 2}})
        self.assertEqual([grid.shown_text(row, 1) for row in range(5)],
                         ["1.25e-04", "1.23e+00", "1.23e+04", "5.00e-01", ""])
        self.assertEqual([grid.shown_text(row, 3) for row in range(5)], ["4", "4", "12", "9999", "0"])
        self.assertEqual(grid.cell_text(1, 1), "1.23456789")  # Copy keeps the classic text of the stored number.
        self.assertEqual(data.raw.iat[1, 1], 1.23456789012345)
        self.assertTrue(app.dirty)
        self.use("it")
        grid.set_number_formats(data.displayed_number_formats)
        self.assertEqual(grid.shown_text(1, 1), "1,23e+00")
        self.use("en")

        app.apply_worksheet_history()
        self.root.update()
        self.assertIs(app.current_grid, grid)
        self.assertEqual(data.number_formats, {})
        self.assertEqual(grid.shown_text(1, 1), "1.23456789")
        app.apply_worksheet_history(redo=True)
        self.root.update()
        self.assertEqual(grid.shown_text(1, 1), "1.23e+00")

        grid.select_block(0, 1, 4, 1)
        self.format(("reset", None))
        self.assertEqual(data.number_formats, {"Risposta": {"mode": "scientific", "digits": 2}})
        grid.select_block(0, 0, 4, 0)
        self.format(("apply", {"mode": "fixed", "digits": 1}))
        self.assertEqual(len(self.errors), 1)

    def test_result_tabs_keep_their_own_formats(self):
        app = self.app
        frame = pd.DataFrame({"Dose": [0.5, 1, 2, 4, 8, 16, 32, 64],
                              "Response": [2.1, 3.9, 6.2, 8.1, 9.8, 12.3, 13.1, 13.5]})
        app._add_tables({"Fit": frame})
        run = self.module.Run("Deming regression", "Fit", {"X": "Dose", "Y": "Response", "Y series": [],
                                                           "Uncertainty input": "Variance ratio",
                                                           "Y / X error variance": 1.0})
        app.add_result(run, app.compute(run, app.tables["Fit"].frame()))
        self.root.update()
        app.show("result", len(app.runs) - 1)
        self.root.update()
        tabs = app.result_tabs
        names = [tabs.tab(tab, "text") for tab in tabs.tabs()]
        tabs.select(names.index("Data"))
        self.root.update()
        data_grid = tabs.nametowidget(tabs.tabs()[names.index("Data")])
        data_grid.cells.select_block(0, 1, 7, 1)
        self.format(("apply", {"mode": "fixed", "digits": 2}))
        tabs.select(names.index("Pairs"))
        self.root.update()
        pairs = tabs.nametowidget(tabs.tabs()[names.index("Pairs")])
        pairs.cells.select_block(0, 2, 7, 2)
        self.format(("apply", {"mode": "scientific", "digits": 1}))
        self.assertEqual(app.tables["Fit"].result_number_formats[run.slot],
                         {"Data": {1: {"mode": "fixed", "digits": 2}},
                          "Pairs": {2: {"mode": "scientific", "digits": 1}}})
        self.assertEqual(data_grid.cells.shown_text(0, 1), "0.50")
        self.assertEqual(data_grid.cells.shown_text(0, 2), "2.1")
        value = run.result.tables["Pairs"].iat[0, 1]
        self.assertEqual(pairs.cells.shown_text(0, 2), format_number(value, {"mode": "scientific", "digits": 1}))
        self.assertNotEqual(pairs.cells.cell_text(0, 2), pairs.cells.shown_text(0, 2))
        pairs.cells.select_block(0, 0, 0, 0)
        self.format(("apply", {"mode": "fixed", "digits": 1}))
        self.assertTrue(self.errors, "row titles alone take no number format")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "formats.alab"
            self.module.save_project(path, app.tables)
            reopened = self.module.load_project(path)["Fit"]
        self.assertEqual(reopened.result_number_formats[run.slot], app.tables["Fit"].result_number_formats[run.slot])

    def test_real_dialog_cancels_on_escape_and_confirms_on_return(self):
        import tkinter as tk
        app = self.app
        app._add_tables({"celle": FIXTURE.copy()})
        self.root.update()
        grid = app.current_grid
        grid.select_block(0, 1, 0, 1)
        seen = []

        def press(key, mode=None, digits=None):
            def act():
                dialog = [widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel)][-1]
                if mode:
                    dialog.mode.set(mode)
                    dialog.mode_changed()
                if digits is not None:
                    dialog.digits.set(str(digits))
                    dialog.digits_changed()
                seen.append((dialog.shown.cget("text"), str(dialog.reset_button.state())))
                dialog.event_generate(key)
            return act

        self.root.after(300, press("<Escape>", "significant", 2))
        app.change_number_format()
        self.assertEqual(seen[0][0], "0.00013")
        self.assertIn("disabled", seen[0][1])
        self.assertEqual(app.tables["celle"].number_formats, {})
        self.root.after(300, press("<Return>", "fixed", 5))
        app.change_number_format()
        self.assertEqual(app.tables["celle"].number_formats, {"Dose": {"mode": "fixed", "digits": 5}})
        self.assertEqual(grid.shown_text(0, 1), "0.00013")
        # Out of range digits keep the dialog open with the hint.
        started = time.monotonic()

        def out_of_range():
            dialog = [widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel)][-1]
            dialog.digits.set("40")
            dialog.ok()
            seen.append(dialog.problem.cget("text"))
            dialog.cancel()
        self.root.after(300, out_of_range)
        app.change_number_format()
        self.assertTrue(seen[-1])
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(app.tables["celle"].number_formats, {"Dose": {"mode": "fixed", "digits": 5}})
