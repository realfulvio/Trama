"""The real joint-fit dialog validates profiles without running the solver."""
import traceback
from unittest.mock import patch

import pandas as pd

from analisi import ui_theme
from analisi.global_custom_fit import GLOBAL_CUSTOM_EQUATION
from analisi.parameter_intervals import METHOD, PROFILE
from tests.test_graph_i18n import TkCase
from tests.test_global_custom_profiles import FRAME, RECIPE


class GlobalProfileDialogTests(TkCase):
    def drive(self, action, *, frame=FRAME, **options):
        from tramastat import AnalysisDialog
        seen = {}

        def step():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            if dialog.grab_current() is not dialog:
                self.root.after(20, step)
                return
            try:
                dialog.update_idletasks()
                action(dialog)
            except Exception:
                seen['error'] = traceback.format_exc()
            finally:
                dialog.result = None
                dialog.cancel()

        self.root.deiconify()
        self.root.geometry('1000x700+0+0')
        ui_theme.configure(self.root)
        self.root.after(100, step)
        AnalysisDialog(self.root, frame.copy(), current=(GLOBAL_CUSTOM_EQUATION, {**RECIPE, **options}),
                       only=GLOBAL_CUSTOM_EQUATION)
        self.root.withdraw()
        self.assertNotIn('error', seen, seen.get('error'))

    def test_profile_choice_on_output_page_defers_the_joint_fit(self):
        def action(d):
            self.assertIn(METHOD, d.controls)
            self.assertEqual(d.field_rows[METHOD][1].master, d.field_rows['Confidence level (%)'][1].master)
            d.controls[METHOD][1].set(PROFILE)
            with patch('tramastat.analyse', side_effect=AssertionError('Must run on worker')):
                self.assertTrue(d.validate())
            self.assertIsNone(d.processing_result)
            self.assertEqual(d.result[1][METHOD], PROFILE)
        self.drive(action)

    def test_legacy_wald_keeps_its_original_recipe_key_set(self):
        def action(d):
            self.assertTrue(d.validate())
            self.assertNotIn(METHOD, d.result[1])
        self.drive(action)

    def test_translated_choice_keeps_canonical_value_and_separate_levels(self):
        self.use('it')
        def action(d):
            self.assertEqual(d.field_rows[METHOD][0].cget('text'), 'Intervalli dei parametri')
            self.assertIn('Profilo di verosimiglianza', d.field_rows[METHOD][1].cget('values'))
            d.field_rows[METHOD][1].set('Profilo di verosimiglianza')
            d.field_rows[METHOD][1].event_generate('<<ComboboxSelected>>')
            d.update()
            d.controls['Confidence level (%)'][1].set('90,5')
            d.controls['Curve band'][1].set('Confidence')
            d.controls['Response level (%)'][1].set('99')
            self.assertTrue(d.validate())
            self.assertEqual(d.result[1][METHOD], PROFILE)
            self.assertEqual(d.result[1]['Confidence level (%)'], 90.5)
            self.assertEqual(d.result[1]['Response level (%)'], 99.)
        self.drive(action)

    def test_budget_error_focuses_output_and_can_be_corrected_in_place(self):
        self.use('it')
        def action(d):
            d.controls[METHOD][1].set(PROFILE)
            with patch('tramastat.messagebox.showerror') as error:
                self.assertFalse(d.validate())
            self.assertIn('5000', error.call_args.args[1])
            self.assertIn('complessive', error.call_args.args[1])
            self.assertEqual(d.focus_get(), d.field_rows[METHOD][1])
            d.controls[METHOD][1].set('Symmetric (Wald)')
            self.assertTrue(d.validate())
            self.assertNotIn(METHOD, d.result[1])
        self.drive(action, frame=pd.concat([FRAME]*417, ignore_index=True))
