"""The startup UI is lightweight, animated, and owns only its own window."""
import importlib
import importlib.util
import json
import subprocess
import sys
import threading
import time
from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace

from tests.test_graph_i18n import TkCase


class StartupImportTests(TestCase):
    def test_startup_import_does_not_load_the_analysis_stack_or_open_a_window(self):
        self.assertIsNotNone(importlib.util.find_spec('trama_startup'), 'The lightweight startup UI is missing')
        command = "import trama_startup,sys,json,tkinter; print(json.dumps({'heavy': sorted(n for n in sys.modules if n.split('.')[0] in {'numpy','scipy','pandas','matplotlib','analisi'}), 'root': tkinter._default_root is not None}))"
        run = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True, check=True)
        state = json.loads(run.stdout)
        self.assertEqual(state, {'heavy': [], 'root': False})


class StartupWindowTests(TkCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('trama_startup'), 'The animated startup UI is missing')
        return importlib.import_module('trama_startup')

    def test_spinner_advances_without_moving_the_window_and_close_is_idempotent(self):
        module = self.module()
        screen = module.StartupScreen(self.root, language='it')
        self.root.update()
        original_geometry = screen.geometry()
        before = float(screen.canvas.itemcget(screen.arc, 'start'))
        deadline = time.monotonic()+.2
        while time.monotonic() < deadline:
            self.root.update(); time.sleep(.01)
        after = float(screen.canvas.itemcget(screen.arc, 'start'))
        self.assertNotEqual(before, after)
        self.assertEqual(screen.geometry(), original_geometry)
        self.assertEqual(screen.message.cget('text'), 'Caricamento in corso…')
        self.assertTrue(screen.winfo_viewable())
        screen.close(); screen.close()
        self.assertFalse(screen.winfo_exists())
        self.assertTrue(self.root.winfo_exists())

    def test_startup_loads_off_thread_then_hands_the_same_root_to_the_app_on_main_thread(self):
        module = self.module()
        entered = threading.Event(); release = threading.Event(); observations = {}
        created = []; original = module.StartupScreen
        class Screen(original):
            def __init__(inner, root, **kwargs):
                super().__init__(root, **kwargs); created.append(inner)
                def probe():
                    observations['arc_at_start'] = float(inner.canvas.itemcget(inner.arc, 'start'))
                    def finish_probe():
                        observations['arc_after_wait'] = float(inner.canvas.itemcget(inner.arc, 'start'))
                        release.set()
                    root.after(150, finish_probe)
                root.after(40, probe)
        def load():
            observations['loader_thread'] = threading.current_thread()
            entered.set()
            if not release.wait(5): raise TimeoutError('Startup animation did not run')
            return SimpleNamespace(main=main)
        def main(*, root, on_ready, standard_only):
            observations['main_thread'] = threading.current_thread()
            observations['same_root'] = created[0].master is root
            self.assertTrue(standard_only)
            self.assertTrue(created[0].winfo_exists())
            root.deiconify(); root.update_idletasks(); on_ready()
            self.assertFalse(created[0].winfo_exists())
        with patch.object(module, 'StartupScreen', Screen), patch.object(module, '_load_app', load), \
             patch.object(module.messagebox, 'showerror'):
            self.assertEqual(module.launch(), 0)
        self.assertTrue(entered.is_set())
        self.assertIsNot(observations['loader_thread'], threading.main_thread())
        self.assertIs(observations['main_thread'], threading.main_thread())
        self.assertTrue(observations['same_root'])
        self.assertNotEqual(observations['arc_at_start'], observations['arc_after_wait'])

    def test_import_failure_closes_splash_and_reports_error_on_main_thread(self):
        module = self.module(); observed = {}
        def report(*args, **kwargs):
            observed['thread'] = threading.current_thread(); observed['text'] = args[1]
        with patch.object(module, '_load_app', side_effect=RuntimeError('broken package')), \
             patch.object(module.messagebox, 'showerror', side_effect=report):
            self.assertEqual(module.launch(), 1)
        self.assertIn('broken package', observed['text'])
        self.assertIs(observed['thread'], threading.main_thread())
