"""The splash is on screen before the scientific stack is imported, not after.

Importing NumPy, pandas, SciPy and matplotlib takes two to three seconds (seven on a first launch, when matplotlib
builds its font cache). The splash exists to cover that wait, so it must be shown first.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("numpy", "pandas", "scipy", "matplotlib", "statsmodels", "analisi")
# Start the program as ``python -m trama_qt`` does, with the event loop replaced by a no-op, and note what was
# already imported when the splash was shown.
START = f"""
import json, os, sys
from PySide6.QtWidgets import QApplication, QSplashScreen

seen = {{}}
show = QSplashScreen.show


def recording(self):
    seen.setdefault("loaded_at_splash", [name for name in {HEAVY!r} if name in sys.modules])
    return show(self)


QSplashScreen.show = recording
QApplication.exec = lambda *arguments: 0
from trama_qt.app import main

status = main(["trama"])
seen["status"] = status
seen["loaded_at_window"] = [name for name in {HEAVY!r} if name in sys.modules]
print(json.dumps(seen), flush=True)
os._exit(0)
"""


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SplashFirstTests(unittest.TestCase):
    def test_the_splash_is_shown_before_the_scientific_stack_loads(self):
        with tempfile.TemporaryDirectory() as home:
            environment = {**os.environ, "HOME": home, "XDG_CONFIG_HOME": home, "APPDATA": home,
                           "MPLCONFIGDIR": os.path.join(home, "mpl"), "QT_QPA_PLATFORM": "offscreen"}
            environment.pop("MPLBACKEND", None)
            done = subprocess.run([sys.executable, "-c", START], cwd=ROOT, env=environment, capture_output=True,
                                  text=True, timeout=600)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(lines, done.stderr[-2000:])
        seen = json.loads(lines[-1])
        self.assertEqual(seen["status"], 0)
        self.assertIn("loaded_at_splash", seen, "no splash was shown")
        self.assertEqual(seen["loaded_at_splash"], [])
        self.assertIn("numpy", seen["loaded_at_window"])  # the stack did load, after the splash

    def test_the_splash_image_is_the_one_of_the_theme(self):
        from trama_qt import app, theme

        logo = app.splash_logo()
        self.assertEqual(logo, theme.ASSETS / "brand" / "trama-wordmark-light.png")
        self.assertTrue(logo.is_file())


if __name__ == "__main__":
    unittest.main()
