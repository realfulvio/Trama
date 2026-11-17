"""The real custom-equation dialog keeps profile jobs off the GUI thread."""
import traceback
from unittest.mock import patch

from analisi import ui_theme
from analisi.custom_fit import CUSTOM_EQUATION
from analisi.parameter_intervals import METHOD, PROFILE
from tests.test_graph_i18n import TkCase
from tests.test_custom_parameter_profiles import FRAME, RECIPE


class CustomProfileDialogTests(TkCase):
    def drive(self, action, *, frame=FRAME, **options):
        from tramastat import AnalysisDialog
        seen = {}
        def step():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            if dialog.grab_current() is not dialog:
                self.root.after(20, step); return
            try:
                dialog.update_idletasks(); action(dialog, seen)
            except Exception:
                seen['error'] = traceback.format_exc()
            finally:
                dialog.result = None; dialog.cancel()
        self.root.deiconify(); self.root.geometry('1000x700+0+0'); ui_theme.configure(self.root)
        self.root.after(100, step)
        AnalysisDialog(self.root, frame.copy(), current=(CUSTOM_EQUATION, {**RECIPE, **options}), only=CUSTOM_EQUATION)
        self.root.withdraw(); self.assertNotIn('error', seen, seen.get('error'))
        return seen

    def test_choice_lives_on_output_page_and_fit_is_deferred(self):
        def action(d, _):
            self.assertIn(METHOD, d.controls)
            self.assertEqual(d.field_rows[METHOD][1].master, d.field_rows['Confidence level (%)'][1].master)
            d.controls[METHOD][1].set(PROFILE)
            with patch('tramastat.analyse', side_effect=AssertionError('Must run on worker')):
                self.assertTrue(d.validate())
            self.assertIsNone(d.processing_result)
            self.assertEqual(d.result[1][METHOD], PROFILE)
        self.drive(action)

    def test_unchanged_legacy_wald_dialog_does_not_add_a_recipe_key(self):
        def action(d, _):
            self.assertTrue(d.validate())
            self.assertNotIn(METHOD, d.result[1])
        self.drive(action)

    def test_italian_choice_persists_the_canonical_value(self):
        self.use('it')
        def action(d, _):
            self.assertIn(METHOD, d.controls)
            self.assertEqual(d.field_rows[METHOD][0].cget('text'), 'Intervalli dei parametri')
            self.assertIn('Profilo di verosimiglianza', d.field_rows[METHOD][1].cget('values'))
            d.field_rows[METHOD][1].set('Profilo di verosimiglianza')
            d.field_rows[METHOD][1].event_generate('<<ComboboxSelected>>'); d.update()
            self.assertTrue(d.validate())
            self.assertEqual(d.result[1][METHOD], PROFILE)
        self.drive(action)

    def test_bad_level_stays_on_its_field_and_is_correctable(self):
        self.use('it')
        def action(d, _):
            self.assertIn(METHOD, d.controls)
            d.controls[METHOD][1].set(PROFILE)
            d.controls['Confidence level (%)'][1].set('100')
            with patch('tramastat.messagebox.showerror') as error:
                self.assertFalse(d.validate())
            self.assertTrue(error.called)
            self.assertEqual(d.focus_get(), d.field_rows['Confidence level (%)'][1])
            self.assertIn('confidenza', error.call_args.args[1].lower())
            d.controls['Confidence level (%)'][1].set('90,5')
            self.assertTrue(d.validate())
            self.assertEqual(d.result[1]['Confidence level (%)'], 90.5)
        self.drive(action)

    def test_profile_budget_error_keeps_the_output_page_reachable(self):
        def action(d, _):
            self.assertIn(METHOD, d.controls)
            d.controls[METHOD][1].set(PROFILE)
            with patch('tramastat.messagebox.showerror') as error:
                self.assertFalse(d.validate())
            self.assertIn('5000', error.call_args.args[1])
            self.assertEqual(d.focus_get(), d.field_rows[METHOD][1])
        import pandas as pd
        self.drive(action, frame=pd.concat([FRAME]*1001, ignore_index=True))
