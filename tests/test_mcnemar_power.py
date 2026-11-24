"""Exact McNemar power and the first sample size that reaches a target.

The oracle enumerates the three pair classes itself. It does not call the module under test.
The Qt half follows the empty-project power-planning test in ``tests/test_qt_shell.py``.
"""
from fractions import Fraction
from math import comb, isclose
from pathlib import Path
import threading
import time
import tracemalloc
import unittest

import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from analisi import mcnemar_power as mp
from analisi.field_error import FieldError
from analisi.i18n import active_language, set_language, translate_message
from analisi.monte_carlo import MonteCarloCancelled
from analisi.paired_proportions import EXACT, mcnemar_summary
from analisi.workbench import GROUPS, analyse

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

ROOT = Path(__file__).resolve().parent.parent
# The package oracle's crossing: r = 1, target 0.17, first N is 6 and N = 7 is lower.
FIXTURE = (Fraction(3, 4), Fraction(1, 4), Fraction(17, 100))
# Default planning case. The first N at alpha 5% is locked below against the same oracle.
MAIN = (Fraction(3, 10), Fraction(1, 10), Fraction(4, 5))


def oracle(n, p01, p10, alpha=Fraction(1, 20)):
    """Power by enumerating gains, losses and concordant pairs. Alpha is inclusive."""
    result = Fraction(0)
    for gains in range(n + 1):
        for losses in range(n - gains + 1):
            discordant = gains + losses
            if not discordant:
                continue
            tail = Fraction(2 * sum(comb(discordant, j) for j in range(min(gains, losses) + 1)), 2 ** discordant)
            if tail <= alpha:
                result += (comb(n, discordant) * comb(discordant, gains) * p01 ** gains
                           * p10 ** losses * (1 - p01 - p10) ** (n - discordant))
    return result


def _rows(options):
    result = mp.analysis(None, options)
    return result, result.tables[mp.METHOD]["Value"].to_dict()


def _target_lines(axes, target):
    found = []
    for line in axes.lines:
        ys = np.asarray(line.get_ydata(), dtype=float)
        if ys.size >= 2 and np.allclose(ys, target):
            found.append(line)
    return found


class OracleGrid(unittest.TestCase):
    def assert_power(self, n, p01, p10, alpha=Fraction(1, 20)):
        expected = float(oracle(n, p01, p10, alpha))
        actual = mp.exact_power(n, float(p01), float(p10), float(alpha))
        self.assertTrue(isclose(actual, expected, abs_tol=2e-13, rel_tol=2e-12),
                        (n, p01, p10, alpha, actual, expected))

    def test_contract_grid(self):
        cases = ((Fraction(3, 10), Fraction(1, 10), Fraction(1, 20)),
                 (Fraction(3, 4), Fraction(1, 4), Fraction(1, 20)),
                 (Fraction(1), Fraction(0), Fraction(1, 32)),
                 (Fraction(0), Fraction(0), Fraction(1, 20)),
                 (Fraction(3, 10), Fraction(3, 10), Fraction(1, 20)))
        for p01, p10, alpha in cases:
            for n in (1, 5, 6, 7, 10, 19, 30):
                with self.subTest(n=n, p01=p01, p10=p10, alpha=alpha):
                    self.assert_power(n, p01, p10, alpha)

    def test_extreme_alpha_requires_enough_discordant_pairs(self):
        for alpha, first_rejection in ((1e-20, 68), (float.fromhex("0x0.0000000000001p-1022"), 1075)):
            with self.subTest(alpha=alpha):
                self.assertEqual(mp.exact_power(first_rejection - 1, 1, 0, alpha), 0.0)
                self.assertEqual(mp.exact_power(first_rejection, 1, 0, alpha), 1.0)
                self.assertEqual(mp.minimum_pairs(1, 0, 0.8, alpha), first_rejection)

    def test_alpha_just_below_exact_tail_does_not_reject(self):
        alpha = np.nextafter(1 / 32, 0.0)
        self.assertEqual(mp.exact_power(6, 1, 0, alpha), 0.0)
        self.assertEqual(mp.exact_power(6, 1, 0, 1 / 32), 1.0)

    def test_alpha_percent_that_underflows_is_a_field_error(self):
        with self.assertRaises(FieldError) as caught:
            mp.check_options({mp.ALPHA: "5e-324"})
        self.assertEqual(caught.exception.field, mp.ALPHA)

    def test_limit_is_5000_pairs(self):
        self.assertEqual(mp.LIMIT, 5000)
        self.assertIn(mp.METHOD, GROUPS["Study Design and Simulation"])

    def test_power_can_fall_and_every_smaller_n_misses_the_fixture(self):
        p01, p10, target = FIXTURE
        self.assertGreater(oracle(6, p01, p10), oracle(7, p01, p10))
        self.assertGreater(mp.exact_power(6, float(p01), float(p10)), mp.exact_power(7, float(p01), float(p10)))
        minimum = next(n for n in range(1, 31) if oracle(n, p01, p10) >= target)
        self.assertEqual(minimum, 6)
        self.assertEqual(mp.minimum_pairs(float(p01), float(p10), float(target), max_pairs=30), 6)
        self.assertIsNone(mp.minimum_pairs(.3, .1, .9, max_pairs=5))
        for n in range(1, minimum):
            with self.subTest(n=n):
                self.assertLess(oracle(n, p01, p10), target)
                self.assertLess(mp.exact_power(n, float(p01), float(p10)), float(target))
        self.assertGreaterEqual(oracle(minimum, p01, p10), target)

    def test_main_target_is_the_first_n_and_not_only_its_predecessor(self):
        p01, p10, target = MAIN
        # The boundary itself is checked by enumeration. Every earlier N is checked too.
        self.assertLess(oracle(83, p01, p10), target)
        self.assertGreaterEqual(oracle(84, p01, p10), target)
        minimum = mp.minimum_pairs(float(p01), float(p10), float(target))
        self.assertEqual(minimum, 84)
        for n in range(1, minimum):
            self.assertLess(mp.exact_power(n, float(p01), float(p10)), float(target), n)
        self.assertGreaterEqual(mp.exact_power(minimum, float(p01), float(p10)), float(target))
        result, rows = _rows({mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: 0.8,
                              mp.P01: 30, mp.P10: 10, mp.GRAPH: True})
        curve = result.tables[mp.CURVE_SHEET]
        self.assertEqual(curve["N"].tolist(), list(range(1, 85)))
        self.assertTrue((curve["Power"].iloc[:-1] < 0.8).all())
        self.assertGreaterEqual(curve["Power"].iloc[-1], 0.8)
        self.assertEqual(rows["N"], 84)
        self.assertLess(rows[mp.PREVIOUS], 0.8)
        self.assertGreaterEqual(rows["Power"], 0.8)
        self.assertEqual(rows["Result"], mp.STATUS_MINIMUM)
        self.assertEqual(rows["Pairs limit"], 5000)

    def test_no_discordance_is_zero_power_and_not_a_null_effect(self):
        self.assertEqual(mp.exact_power(25, 0, 0), 0.0)
        self.assertEqual(mp.exact_power(25, 0.0, 0.0, 0.01), 0.0)
        self.assertIsNone(mp.minimum_pairs(0, 0, 0.05))
        result, rows = _rows({mp.GOAL: mp.POWER_GOAL, mp.ALPHA: 5, mp.PAIRS: 4,
                              mp.P01: 0, mp.P10: 0, mp.GRAPH: True})
        self.assertEqual(rows["Result"], mp.STATUS_NONE)
        self.assertEqual(rows["Power"], 0.0)
        self.assertIn("power is 0", rows["Note"])
        self.assertNotIn("Null effect", rows["Note"])
        curve = result.tables[mp.CURVE_SHEET]
        self.assertEqual(curve["N"].tolist(), [1, 2, 3, 4])
        self.assertEqual(curve["Power"].tolist(), [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(_target_lines(result.figure.axes[0], 0.8), [])

    def test_almost_certain_discordance_stays_finite(self):
        p01, p10 = 1 - 1e-9, 5e-10
        self.assertLess(p01 + p10, 1)
        for n in (1, 6, 7, 20):
            power = mp.exact_power(n, p01, p10)
            self.assertTrue(0 <= power <= 1, (n, power))
        # A discordance of one in a million must not collapse the binomial weights to a zero sum.
        tiny = mp.exact_power(30, 1e-8, 1e-9)
        self.assertTrue(0 <= tiny <= 1)
        self.assertGreater(mp.exact_power(6, 0.999, 0.0005), 0.99)

    def test_probabilities_outside_the_simplex_are_refused(self):
        with self.assertRaises(ValueError):
            mp.exact_power(8, 0.8, 0.3)
        with self.assertRaises(ValueError):
            mp.exact_power(8, -0.1, 0.2)
        with self.assertRaises(ValueError):
            mp.exact_power(8, 1.1, 0)
        # A fraction sum within 1e-12 of 1 is a rounding of a legal design. A larger excess is not.
        mp.exact_power(4, 0.7, 0.3 + 5e-13)
        with self.assertRaises(ValueError):
            mp.exact_power(4, 0.7, 0.3 + 1e-6)
        with self.assertRaises(FieldError) as caught:
            mp.check_options({mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: 0.8,
                              mp.P01: "70,5", mp.P10: 40, mp.GRAPH: False})
        self.assertEqual(caught.exception.field, mp.P10)
        self.assertIn("add up to more than 100", str(caught.exception))
        # 33.3 + 66.7 is 100 at one decimal and can sit a few ulps over 1 after dividing by 100.
        plan = mp.check_options({mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: "5,0", mp.TARGET: "0,8",
                                 mp.P01: "33,3", mp.P10: "66,7", mp.GRAPH: False})
        self.assertLessEqual(plan.discordance, 1)
        self.assertGreater(plan.discordance, 0.999)
        recipe = mp.normalized_options(plan)
        self.assertEqual(recipe[mp.TARGET], 0.8)
        self.assertNotIn(mp.PAIRS, recipe)

    def test_six_discordant_pairs_use_the_exact_p_of_paired_proportions(self):
        alpha = Fraction(1, 32)
        discordant = 6
        rejects = []
        for gains in range(discordant + 1):
            summary = mcnemar_summary(0, gains, discordant - gains, 0, EXACT, 95)
            rejects.append(summary["p"] <= float(alpha))
        # The doubled tail at 0 gains is exactly 1/32, so the inclusive boundary rejects. One gain does not.
        self.assertEqual(rejects, [True, False, False, False, False, False, True])
        self.assertGreater(mcnemar_summary(0, 1, 5, 0, EXACT, 95)["p"], float(Fraction(1, 33)))
        from scipy.stats import binom
        for q in (0, 0.25, 0.5, 0.75, 1):
            expected = sum(float(binom.pmf(gains, discordant, q)) for gains, reject in enumerate(rejects) if reject)
            actual = mp.exact_power(discordant, q, 1 - q, float(alpha))
            self.assertTrue(isclose(actual, expected, abs_tol=2e-12, rel_tol=2e-12), (q, actual, expected))
        self.assertEqual(mp.exact_power(6, 1, 0, float(alpha)), 1)
        self.assertEqual(mp.exact_power(6, 1, 0, float(Fraction(1, 33))), 0)
        # No D from 1 to 6 has an exact p as small as 1/33, so the power is 0 for every r.
        self.assertEqual(mp.exact_power(6, 0.3, 0.2, float(Fraction(1, 33))), 0)

    def test_null_effect_above_alpha_is_unreachable(self):
        self.assertIsNone(mp.minimum_pairs(0.2, 0.2, 0.5))
        power = mp.exact_power(80, 0.2, 0.2, 0.05)
        self.assertLessEqual(power, 0.05 + 1e-9)
        _result, rows = _rows({mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: 0.8,
                               mp.P01: 20, mp.P10: 20, mp.GRAPH: False})
        self.assertEqual(rows["Result"], mp.STATUS_NULL)
        self.assertIn("size of the two-sided", rows["Note"])
        self.assertIn("target above alpha", rows["Note"])
        self.assertLessEqual(rows["Maximum power"], 0.05 + 1e-9)
        self.assertEqual(rows["Pairs limit"], 5000)

    def test_curve_has_every_integer_and_the_target_line_only_for_sample_size(self):
        result, _rows_sample = _rows({mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: float(FIXTURE[2]),
                                      mp.P01: 75, mp.P10: 25, mp.GRAPH: True})
        curve = result.tables[mp.CURVE_SHEET]
        self.assertEqual(curve["N"].tolist(), list(range(1, 7)))
        for n, power in zip(curve["N"], curve["Power"]):
            self.assertTrue(isclose(power, mp.exact_power(int(n), 0.75, 0.25), abs_tol=2e-12, rel_tol=2e-12))
        axes = result.figure.axes[0]
        self.assertEqual(len(_target_lines(axes, float(FIXTURE[2]))), 1)
        self.assertEqual(axes.get_ylim(), (0.0, 1.0))
        locator = axes.xaxis.get_major_locator()
        self.assertIsInstance(locator, MaxNLocator)
        self.assertTrue(getattr(locator, "integer", getattr(locator, "_integer", False)))

        power_goal, rows = _rows({mp.GOAL: mp.POWER_GOAL, mp.ALPHA: 5, mp.PAIRS: 12,
                                  mp.P01: "30,5", mp.P10: "10,5", mp.GRAPH: True})
        curve = power_goal.tables[mp.CURVE_SHEET]
        self.assertEqual(curve["N"].tolist(), list(range(1, 13)))
        self.assertEqual(_target_lines(power_goal.figure.axes[0], 0.8), [])
        self.assertNotIn("Target power", rows)
        self.assertEqual(rows["N"], 12)
        self.assertNotIn(mp.PREVIOUS, rows)

    def test_unreachable_search_to_5000_cancel_and_peak(self):
        self.assertTrue(issubclass(mp.McNemarPowerCancelled, MonteCarloCancelled))
        confirmed = mp.minimum_pairs(0.75, 0.25, 0.17, max_pairs=30)
        self.assertEqual(confirmed, 6)
        event = threading.Event()
        event.set()
        with self.assertRaises(mp.McNemarPowerCancelled):
            mp.minimum_pairs(0.3, 0.1, 0.8, cancel=event)
        with self.assertRaises(mp.McNemarPowerCancelled):
            analyse(mp.METHOD, pd.DataFrame(), {mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: 0.8,
                                                mp.P01: 30, mp.P10: 10, mp.GRAPH: False}, cancel=lambda: True)
        self.assertEqual(confirmed, 6)

        fired = {}

        def cancel():
            if "armed" not in fired:
                fired["armed"] = time.perf_counter()
                return False
            if time.perf_counter() - fired["armed"] < 0.02:
                return False
            fired["at"] = time.perf_counter()
            return True

        with self.assertRaises(mp.McNemarPowerCancelled):
            mp.minimum_pairs(0.12, 0.10, 0.9, max_pairs=5000, cancel=cancel)
        latency = time.perf_counter() - fired["at"]
        self.assertLess(latency, 0.5, latency)
        self.assertEqual(confirmed, 6)
        held, held_rows = _rows({mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: 0.17,
                                mp.P01: 75, mp.P10: 25, mp.GRAPH: False})
        snapshot = list(held.tables[mp.METHOD]["Value"].items())
        with self.assertRaises(mp.McNemarPowerCancelled):
            mp.analysis(None, {mp.GOAL: mp.POWER_GOAL, mp.ALPHA: 5, mp.PAIRS: 5000,
                               mp.P01: 12, mp.P10: 10, mp.GRAPH: False}, cancel=event)
        self.assertEqual(list(held.tables[mp.METHOD]["Value"].items()), snapshot)
        self.assertEqual(held_rows["N"], 6)

        tracemalloc.start()
        started = time.perf_counter()
        result = mp.analysis(None, {mp.GOAL: mp.SAMPLE_SIZE, mp.ALPHA: 5, mp.TARGET: 0.9,
                                    mp.P01: 12, mp.P10: 10, mp.GRAPH: True})
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rows = result.tables[mp.METHOD]["Value"].to_dict()
        curve = result.tables[mp.CURVE_SHEET]
        self.assertEqual(rows["Result"], mp.STATUS_NOT_REACHED)
        self.assertEqual(curve["N"].tolist(), list(range(1, 5001)))
        self.assertEqual(len(_target_lines(result.figure.axes[0], 0.9)), 1)
        self.assertEqual(rows["N"], rows["N at maximum"])
        self.assertAlmostEqual(rows["Maximum power"], float(curve["Power"].max()))
        self.assertLess(rows["Maximum power"], 0.9)
        self.assertLess(elapsed, 15, elapsed)
        self.assertLess(peak, 32 * 2 ** 20, peak)
        print(f"mcnemar 5000-pair search: {elapsed:.3f} s, cancel latency {latency:.4f} s, "
              f"tracemalloc peak {peak / 2 ** 20:.2f} MiB")


class Messages(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_language, active_language())

    def test_italian_messages_match_the_engine_text(self):
        set_language("it")
        samples = {
            f"{mp.P10} must be a percentage from 0 to 100, including 0 and 100.": "percentuale",
            f"{mp.ALPHA} must be a percentage strictly between 0 and 100.": "strettamente",
            f"{mp.PAIRS} must be a whole number from 1 to 5,000.": "5.000",
            f"{mp.TARGET} must be strictly between 0 and 1.": "strettamente",
            f"{mp.P01} must be finite.": "finito",
            f"{mp.P01} must be a number.": "numero",
            f"{mp.GRAPH} must be on or off.": "attivo",
            f"{mp.P01} and {mp.P10} add up to more than 100.": "superano 100",
            "Choose Sample size or Power for Goal.": "Dimensione del campione",
        }
        for english, fragment in samples.items():
            translated = translate_message(english, mp.ERROR_PREFIX, convert={"field": lambda name: name})
            self.assertIn(fragment, translated, english)
            self.assertNotEqual(translated, english)


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtEmptyProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.window.error = lambda error: self.fail(f"error shown: {error}")
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def test_empty_project_comma_sum_swap_save_reopen_export(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog
        from analisi.i18n import tr
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        action = self.window.actions["paired_power"]
        self.assertTrue(action.isEnabled())
        self.assertTrue(self.window.actions["power"].isEnabled())
        self.assertFalse(self.window.project.tables)

        with patch.object(AnalysisDialog, "exec", return_value=AnalysisDialog.DialogCode.Rejected):
            action.trigger()
        self.assertFalse(self.window.project.tables)
        self.assertFalse(self.window.project.dirty)

        def plan(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertEqual([dialog.tabs.tabText(i) for i in range(3)], ["Disegno", "Effetto", "Curva"])
            self.assertEqual(dialog.heading.text(), "Potenza per proporzioni appaiate")
            self.assertFalse(dialog.controls[mp.TARGET][1].isHidden())
            self.assertTrue(dialog.controls[mp.PAIRS][1].isHidden())
            dialog.controls[mp.PAIRS][1].setText("nope")  # Hidden: the sample-size goal must ignore it.
            dialog.controls[mp.P01][1].setText("70,5")
            dialog.controls[mp.P10][1].setText("40")
            dialog.run_button.click()
            self.app.processEvents()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, mp.P10)
            self.assertIs(dialog.focusWidget(), dialog.controls[mp.P10][1])
            self.assertIn("sommati superano 100", dialog.banner.text())
            goal = dialog.controls[mp.GOAL][1]
            goal.setCurrentIndex(goal.findData(mp.POWER_GOAL))
            self.app.processEvents()
            self.assertFalse(dialog.controls[mp.PAIRS][1].isHidden())
            self.assertTrue(dialog.controls[mp.TARGET][1].isHidden())
            # The previous sum is still illegal. A comma in the pair count is checked only after
            # the visible percents pass, so replace them before asking the pairs field to focus.
            dialog.controls[mp.P01][1].setText("30")
            dialog.controls[mp.P10][1].setText("10")
            dialog.controls[mp.PAIRS][1].setText("8,0")
            dialog.run_button.click()
            self.app.processEvents()
            self.assertEqual(dialog.error_field, mp.PAIRS)
            self.assertIs(dialog.focusWidget(), dialog.controls[mp.PAIRS][1])
            self.assertIn("Numero di coppie", dialog.banner.text())
            goal.setCurrentIndex(goal.findData(mp.SAMPLE_SIZE))
            dialog.controls[mp.ALPHA][1].setText("5,0")
            dialog.controls[mp.TARGET][1].setText("0,8")
            dialog.controls[mp.P01][1].setText("30")
            dialog.controls[mp.P10][1].setText("10")
            self.app.processEvents()
            note = tr("mcnemar.power.note.effect", difference="20", discordance="40")
            self.assertIn(note, [label.text() for label in dialog.findChildren(type(dialog.banner))])
            dialog.controls[mp.GRAPH][1].setChecked(True)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", plan):
            action.trigger()
            self.wait()
        self.assertEqual(len(self.window.project.tables), 1)
        run, = self.window.project.runs
        self.assertEqual(run.method, mp.METHOD)
        self.assertEqual(run.options[mp.P01], 30)
        self.assertEqual(run.options[mp.P10], 10)
        self.assertEqual(run.options[mp.TARGET], 0.8)
        self.assertNotIn(mp.PAIRS, run.options)
        report = run.result.tables[mp.METHOD]["Value"]
        self.assertEqual(report["N"], 84)
        self.assertGreaterEqual(report["Power"], 0.8)
        self.assertLess(report[mp.PREVIOUS], 0.8)
        self.assertAlmostEqual(report["Expected difference"], 0.2)
        self.assertAlmostEqual(report["Alternative"], 0.75)
        first_power = float(report["Power"])
        self.assertEqual(run.result.tables[mp.CURVE_SHEET]["N"].tolist(), list(range(1, 85)))

        def swap(dialog):
            dialog.show()
            self.app.processEvents()
            dialog.controls[mp.P01][1].setText("10")
            dialog.controls[mp.P10][1].setText("30")
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        self.window.open_sheet(("result", 0))
        self.wait()
        with patch.object(AnalysisDialog, "exec", swap):
            self.window.change_parameters()
            self.wait()
        run, = self.window.project.runs
        report = run.result.tables[mp.METHOD]["Value"]
        self.assertEqual(run.options[mp.P01], 10)
        self.assertEqual(run.options[mp.P10], 30)
        self.assertEqual(report["N"], 84)
        self.assertAlmostEqual(report["Power"], first_power, places=12)
        self.assertAlmostEqual(report["Expected difference"], -0.2)
        self.assertAlmostEqual(report["Alternative"], 0.25)
        recipe = run.options.copy()
        path = self.folder / "paired-power.alab"
        self.window.project.save(path)
        self.assertTrue(self.window.close_project())
        self.assertTrue(self.window.project.is_empty())
        set_language("en")
        self.window.open_path(path)
        run, = self.window.project.runs
        self.assertEqual(run.options, recipe)
        matches = self.window.navigator.findItems(run.name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
        self.assertIn(("graph", 0), [item.data(0, Qt.ItemDataRole.UserRole) for item in matches])
        self.window.open_sheet(("result", 0))
        self.wait()
        self.assertEqual(run.result.tables[mp.METHOD]["Value"]["N"], 84)
        self.assertAlmostEqual(run.result.tables[mp.METHOD]["Value"]["Expected difference"], -0.2)
        csv_path = self.folder / "paired-power.csv"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(csv_path), "CSV (*.csv)")):
            self.window.export()
        exported = pd.read_csv(csv_path, index_col=0)
        self.assertEqual(float(exported.loc["N", "Value"]), 84)
        self.assertAlmostEqual(float(exported.loc["Expected difference", "Value"]), -0.2)
        self.window.open_sheet(("graph", 0))
        self.wait()
        svg = self.folder / "paired-power.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        self.assertIn("<svg", svg.read_text(encoding="utf-8"))

    def test_cancel_does_not_replace_a_confirmed_result(self):
        from unittest.mock import patch
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("en")
        self.window._ask = MainWindow._ask.__get__(self.window)

        def plan(dialog):
            dialog.show()
            dialog.controls[mp.GRAPH][1].setChecked(False)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", plan):
            self.window.actions["paired_power"].trigger()
            self.wait()
        run, = self.window.project.runs
        before_options = dict(run.options)
        before_values = run.result.tables[mp.METHOD]["Value"].tolist()
        self.assertEqual(before_options[mp.P01], 30)

        def slow(dialog):
            dialog.show()
            goal = dialog.controls[mp.GOAL][1]
            goal.setCurrentIndex(goal.findData(mp.POWER_GOAL))
            dialog.controls[mp.PAIRS][1].setText("5000")
            dialog.controls[mp.P01][1].setText("12")
            dialog.controls[mp.P10][1].setText("10")
            dialog.controls[mp.GRAPH][1].setChecked(False)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        self.window.open_sheet(("result", 0))
        self.wait()
        with patch.object(AnalysisDialog, "exec", slow):
            self.window.change_parameters()
        self.assertIsNotNone(self.window.job)
        self.window.cancel_calculation()
        self.wait()
        run, = self.window.project.runs
        self.assertEqual(run.options, before_options)
        self.assertEqual(run.result.tables[mp.METHOD]["Value"].tolist(), before_values)
        self.assertIsNone(run.calculation_error)
