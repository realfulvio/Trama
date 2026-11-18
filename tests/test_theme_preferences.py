"""Preference and real-widget acceptance for optional shell themes."""
import json
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

from analisi import ui_theme
from analisi.i18n import save_language, set_language, ui
from analisi.theme_preferences import load_ribbon_expanded, load_theme, save_ribbon_expanded, save_theme, ThemeDialog


class PreferenceTests(unittest.TestCase):
    def test_defaults_and_unknown_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            self.assertEqual(load_theme(path), 'modern')
            for content in ('broken', 'null', '[]', '{"language": "it"}'):
                path.write_text(content)
                self.assertEqual(load_theme(path), 'modern')
            for content in ('{"theme": "future"}', '{"theme": []}'):
                path.write_text(content)
                self.assertEqual(load_theme(path), 'standard')

    def test_theme_and_language_preserve_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            path.write_text('{"other": 17}')
            save_language(path, 'it')
            save_theme(path, 'modern')
            save_language(path, 'en')
            self.assertEqual(json.loads(path.read_text()), {'language':'en','theme':'modern','other':17})
            save_theme(path, 'standard')
            self.assertEqual(load_theme(path), 'standard')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                save_theme(path, 'bogus')
            self.assertEqual(path.read_bytes(), before)

    def test_atomic_write_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            save_theme(path, 'standard')
            with patch('analisi.theme_preferences.os.replace', side_effect=OSError('readonly')):
                with self.assertRaises(OSError):
                    save_theme(path, 'modern')
            self.assertEqual(load_theme(path), 'standard')
            self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_ribbon_preference_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            self.assertFalse(load_ribbon_expanded(path))
            save_theme(path, 'modern')
            save_language(path, 'it')
            save_ribbon_expanded(path, True)
            self.assertTrue(load_ribbon_expanded(path))
            self.assertEqual(json.loads(path.read_text()), {'theme':'modern','language':'it','ribbon_expanded':True})
            save_ribbon_expanded(path, False)
            self.assertFalse(load_ribbon_expanded(path))


class ThemeWidgetTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('1000x690+0+0')
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'preferences.json'
        self.errors = []
        set_language('it')

    def tearDown(self):
        ui_theme.select_theme('standard')
        set_language('en')
        self.root.destroy()
        self.folder.cleanup()

    def test_dialog_apply_cancel_and_failed_write(self):
        def choose():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, ThemeDialog))
            self.assertEqual(dialog.buttons['modern'].cget('text'), 'Tema Moderno')
            dialog.choice.set('modern')
            dialog.ok()
        self.root.after(100, choose)
        dialog = ThemeDialog(self.root, self.path, error=self.errors.append)
        self.assertTrue(dialog.saved)
        self.assertEqual(load_theme(self.path), 'modern')
        def cancel():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, ThemeDialog))
            dialog.choice.set('standard')
            dialog.cancel()
        self.root.after(100, cancel)
        ThemeDialog(self.root, self.path, error=self.errors.append)
        self.assertEqual(load_theme(self.path), 'modern')
        def fail():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, ThemeDialog))
            with patch('analisi.theme_preferences.save_theme', side_effect=OSError('readonly')):
                self.assertFalse(dialog.validate())
            self.assertFalse(dialog.saved)
            dialog.cancel()
        self.root.after(100, fail)
        ThemeDialog(self.root, self.path, error=self.errors.append)
        self.assertEqual(len(self.errors), 1)

    def test_modern_startup_grid_and_all_commands_then_standard(self):
        import pandas as pd
        import tramastat
        from analisi.ui_shell import CommandSearch, ModernRibbon
        with patch.object(tramastat, 'config_path', return_value=self.path):
            app = tramastat.App(self.root)
        self.assertIsInstance(app.ribbon, ModernRibbon)
        self.assertIn(('Settings', 'Theme…'), app.menu_entries)
        frame = pd.DataFrame({'X':[1,2,3], 'Control [1]':[2,3,4], 'Control [2]':[3,4,5],
                              'Treatment [1]':[4,5,6], 'Treatment [2]':[5,6,7]})
        app._add_tables({'Dose-response': frame})
        grid = app.current_grid
        grid.select_block(0,1,1,2)
        grid.draw()
        self.root.update()
        for width in (820, 1000, 1600):
            app.ribbon.fit(width)
            self.assertLessEqual(app.ribbon.winfo_reqwidth(), width)
        self.assertTrue({'Undo','Redo','Analyze…','Paste Special…','New Info sheet…','Format'} <= set(app.ribbon.buttons))
        ribbon = app.ribbon
        self.assertFalse(ribbon.tabs['format'].winfo_ismapped())
        ribbon.tabs['file'].invoke()
        self.root.update()
        self.assertTrue(ribbon.tabs['file'].instate(['selected']))
        self.assertTrue(ribbon.buttons['Save'].winfo_ismapped())
        with patch.object(tramastat, 'config_path', return_value=self.path):
            ribbon.tabs['home'].invoke()
            ribbon.toggle.invoke()
            self.root.update()
            self.assertTrue(load_ribbon_expanded(self.path))
            self.assertTrue(ribbon.buttons['Paste Special…'].winfo_ismapped())
            ribbon.toggle.invoke()
            self.assertFalse(load_ribbon_expanded(self.path))
        label = ui('Show or hide Navigator')
        matched = []

        def choose_command():
            dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, CommandSearch))
            dialog.query.set(label)
            matched.extend(dialog.results.get(0, 'end'))
            if dialog.results.curselection():
                dialog.ok()
            else:
                dialog.cancel()

        before = app.show_navigator
        self.root.after(100, choose_command)
        ribbon.search.invoke()
        self.assertIn(label, matched)
        self.assertNotEqual(app.show_navigator, before)
        self.assertEqual(grid.anchor, (0,1))
        self.assertEqual(grid.head, (1,2))
        colors = {grid.canvas.itemcget(i, 'outline') for i in grid.canvas.find_all()
                  if grid.canvas.type(i) == 'rectangle'}
        self.assertIn(ui_theme.ACTIVE_CELL, colors)
        self.assertEqual(ui_theme.CHROME, '#ffffff')
        self.assertEqual(ui_theme.SERIES[0], '#0c9c92')
        app.worker.shutdown(wait=True)
        ui_theme.configure(self.root, 'standard')
        self.assertEqual(ui_theme.CHROME, '#f4f6f8')

    def test_modern_analysis_picker_keeps_the_same_recipe_as_standard(self):
        import pandas as pd
        from analisi.graph_language_smoke import drive_mapped_dialog
        from tramastat import AnalysisDialog

        frame = pd.DataFrame({"X": [1, 2, 3], "Y": [2, 5, 6]})
        options = {"X": "X", "Y": "Y", "Y / X error variance": 1.0}
        stored = []
        for theme in ("standard", "modern"):
            ui_theme.configure(self.root, theme)

            def examine(dialog):
                try:
                    dialog.query.set("deming")
                    self.assertEqual(set(dialog.method_by_item.values()), {"Deming regression"})
                    self.assertEqual(dialog.fields.cget("style"), "Analysis.TNotebook" if theme == "modern" else "")
                    self.assertTrue(dialog.validate())
                    stored.append(dialog.result)
                except AssertionError as error:
                    self.errors.append(error)
                finally:
                    dialog.cancel()

            drive_mapped_dialog(self.root, AnalysisDialog, examine, self.errors)
            AnalysisDialog(self.root, frame, current=("Deming regression", options))
        self.assertFalse(self.errors, self.errors)
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0], stored[1])
