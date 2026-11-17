"""Preference and real-widget acceptance for optional shell themes."""
import json
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

from analisi import ui_theme
from analisi.i18n import save_language, set_language
from analisi.theme_preferences import load_theme, save_theme, ThemeDialog


class PreferenceTests(unittest.TestCase):
    def test_defaults_and_unknown_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            self.assertEqual(load_theme(path), 'standard')
            for content in ('broken', 'null', '[]', '{"theme": "future"}', '{"theme": []}'):
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
        from analisi.ui_shell import ModernRibbon
        save_theme(self.path, 'modern')
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
