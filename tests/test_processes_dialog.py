"""Settings → Multicore calculation…: saved, cancelled, invalid and failed choices."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from analisi import parallel
from analisi.i18n import set_language
from analisi.processes_dialog import AUTO, FIXED, SINGLE, ProcessesDialog


class ProcessesDialogTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("800x600+0+0")
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "preferences.json"
        self.path.write_text(json.dumps({"language": "it"}), encoding="utf-8")
        self.errors = []
        set_language("it")

    def tearDown(self):
        set_language("en")
        self.root.destroy()
        self.folder.cleanup()

    def drive(self, action):
        def run():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, ProcessesDialog))
            action(dialog)
        self.root.after(100, run)
        return ProcessesDialog(self.root, self.path, error=self.errors.append, processors=12)

    def test_fixed_single_auto_cancel_and_failures(self):
        def fixed(dialog):
            self.assertEqual(dialog.buttons[AUTO].cget("text"), "Automatico: 8 processi su questo computer")
            self.assertEqual(str(dialog.spin.cget("state")), "disabled")
            dialog.mode.set(FIXED)
            dialog.refresh()
            self.assertEqual(str(dialog.spin.cget("state")), "normal")
            dialog.spin.set("6")
            dialog.ok()
        dialog = self.drive(fixed)
        self.assertTrue(dialog.saved)
        self.assertEqual(dialog.result, 6)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"language": "it", "processes": 6})

        def single(dialog):
            self.assertEqual(dialog.mode.get(), FIXED)
            self.assertEqual(dialog.spin.get(), "6")
            dialog.mode.set(SINGLE)
            dialog.ok()
        self.assertEqual(self.drive(single).result, 1)
        self.assertEqual(parallel.load_setting(self.path), 1)

        def cancel(dialog):
            dialog.mode.set(AUTO)
            dialog.cancel()
        self.assertFalse(self.drive(cancel).saved)
        self.assertEqual(parallel.load_setting(self.path), 1)

        def invalid(dialog):
            dialog.mode.set(FIXED)
            dialog.spin.set("0")
            self.assertFalse(dialog.validate())
            with patch("analisi.processes_dialog.parallel.save_setting", side_effect=OSError("readonly")):
                dialog.mode.set(AUTO)
                self.assertFalse(dialog.validate())
            dialog.cancel()
        self.drive(invalid)
        self.assertEqual(len(self.errors), 2)
        self.assertIn("da 1 a 64", self.errors[0])
        self.assertIn("readonly", self.errors[1])

        def auto(dialog):
            dialog.mode.set(AUTO)
            dialog.ok()
        self.assertEqual(self.drive(auto).result, "auto")
        self.assertEqual(parallel.load_setting(self.path), "auto")


if __name__ == "__main__":
    unittest.main()
