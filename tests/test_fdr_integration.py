"""FDR review cases: reusable adjustments and retained-result correctness."""
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.fdr_control import BH, BKY, BY, FDR_METHOD, METHOD, P_COLUMNS, PLOT, adjust_family, analysis
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import TkCase


class FDRReviewMathTests(TestCase):
    def test_numpy_and_generator_booleans_are_not_p_values(self):
        for values in ([np.bool_(False)], np.array([True], dtype=bool), iter([False])):
            with self.subTest(values=type(values).__name__):
                with self.assertRaisesRegex(ValueError, 'Invalid p family'):
                    adjust_family(values, 'bh', .05)

    def test_request_metadata_identifies_level_specific_adjustments(self):
        frame = pd.DataFrame({'P': [.001, .003, .01, .06, .2, .8]})
        for method, dependent in ((BH, False), (BY, False), (BKY, True)):
            r = analysis(frame, {P_COLUMNS: ['P'], FDR_METHOD: method})
            settings = r.tables['Settings'].set_index('Setting').Value
            self.assertEqual(settings['Adjusted p depends on desired FDR'], dependent)

    def test_bh_by_adjustments_are_level_independent_while_bky_is_not(self):
        values = [.001, .003, .01, .06, .2, .8]
        for method in ('bh', 'by'):
            np.testing.assert_array_equal(adjust_family(values, method, .05)['adjusted'],
                                          adjust_family(values, method, .2)['adjusted'])
        self.assertNotEqual(adjust_family(values, 'bky', .05)['adjusted'],
                            adjust_family(values, 'bky', .2)['adjusted'])

    def test_empty_families_keep_their_labels_and_first_seen_order(self):
        frame = pd.DataFrame({'P': [None]*2000, 'G': [f'group {i}' for i in range(2000)]})
        r = analysis(frame, {P_COLUMNS: ['P'], 'Family columns': ['G']})
        self.assertEqual(len(r.tables['FDR families']), 2000)
        self.assertEqual(r.tables['FDR families'].m.tolist(), [0]*2000)
        self.assertEqual(r.tables['FDR families'].iloc[-1].Family, "G='group 1999' · P")


class FDRRetainedResultTests(TkCase):
    def setUp(self):
        import tramastat
        self.module = tramastat
        self.tmp = tempfile.TemporaryDirectory()
        preferences = Path(self.tmp.name)/'preferences.json'
        save_theme(preferences, 'standard')
        self.root.deiconify()
        with patch.object(tramastat, 'config_path', return_value=preferences):
            self.app = tramastat.App(self.root)
        self.root.geometry('1000x700+0+0')
        self.errors = []
        self.app.error = lambda message: self.errors.append(str(message))
        self.frame = pd.DataFrame({'P': [.01, .03, .2]})
        self.app._add_tables({'Assays': self.frame})
        self.run = tramastat.Run(METHOD, 'Assays', {P_COLUMNS: ['P'], PLOT: True})
        self.app.add_result(self.run, self.app.compute(self.run, self.frame))
        self.root.update()

    def tearDown(self):
        self.wait()
        self.app._clear('')
        self.app.worker.shutdown(wait=True)
        for child in self.root.winfo_children():
            child.destroy()
        self.root.withdraw()
        self.tmp.cleanup()

    def wait(self):
        deadline = time.monotonic()+12
        def poll():
            if self.app.pending is None or time.monotonic() >= deadline:
                self.root.quit()
            else:
                self.root.after(10, poll)

        # Worker-triggered collection can finalize Tk fonts from earlier
        # figures. Tk must be inside its real main loop to service that call,
        # just as it is during normal application use (update() alone is not).
        self.root.after(0, poll)
        self.root.mainloop()
        self.root.update()
        self.assertIsNone(self.app.pending)

    def cancel_reopened_dialog(self):
        seen = []
        deadline = time.monotonic()+8

        def close():
            dialogs = [w for w in self.root.winfo_children() if isinstance(w, self.module.AnalysisDialog)]
            if dialogs and dialogs[0].grab_current() is dialogs[0]:
                d = dialogs[0]
                seen.append(d)
                d.result = None
                d.cancel()
            elif time.monotonic() < deadline:
                self.root.after(15, close)

        self.root.after(15, close)
        return seen

    def test_failed_data_edit_is_marked_stale_and_blocks_export_until_corrected(self):
        previous = self.run.result
        self.app.show('data', 'Assays')
        seen = self.cancel_reopened_dialog()
        self.app.edit_cell(0, 0, '2')
        self.wait()
        self.assertTrue(seen, 'The real recovery dialog must reopen')
        self.assertIs(self.run.result, previous)
        self.assertTrue(self.run.calculation_error)
        self.app.show('result', 0)
        self.assertIsNotNone(self.app.stale_calculation_note())
        tables = set(self.app.tables)
        with patch.object(self.module.filedialog, 'asksaveasfilename') as chooser:
            self.app.export()
        chooser.assert_not_called()
        self.app.use_result_as_data()
        self.assertEqual(set(self.app.tables), tables)
        self.assertEqual(len(self.errors), 2)
        self.app.show('data', 'Assays')
        self.app.edit_cell(0, 0, '.02')
        self.wait()
        self.assertIsNot(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)
        self.assertIsNone(self.app.stale_calculation_note(('result', 0)))

    def test_manual_recalculation_of_changed_data_reopens_and_marks_stale(self):
        previous = self.run.result
        self.app.tables['Assays'].raw.iloc[0, 0] = 2.
        seen = self.cancel_reopened_dialog()
        self.app.recalculate(0)
        self.wait()
        self.assertTrue(seen)
        self.assertIs(self.run.result, previous)
        self.assertTrue(self.run.calculation_error)

    def test_failed_candidate_options_do_not_mark_the_confirmed_data_stale(self):
        previous = self.run.result
        candidate = self.module.Run(METHOD, 'Assays', {P_COLUMNS: ['missing']})
        seen = self.cancel_reopened_dialog()
        recovery = self.app.weighting_recovery(METHOD, candidate.options, 0)
        self.app.start_analysis(candidate, self.frame, 0, recovery=recovery)
        self.wait()
        self.assertTrue(seen)
        self.assertIs(self.app.runs[0], self.run)
        self.assertIs(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)
