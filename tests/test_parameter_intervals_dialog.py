"""Real Analyze widgets: independent parameter/curve levels, validation and worker routing."""
from unittest.mock import patch
import traceback

import numpy as np
import pandas as pd

from analisi import i18n, ui_theme
from analisi.parameter_intervals import METHOD, LEVEL, PROFILE, REPORT_LOG_IC50, WALD
from tests.test_graph_i18n import TkCase

FRAME = pd.DataFrame({'X':np.arange(8.),'Y':[1.2,2.8,4.2,5.9,7.1,8.7,10.4,12.]})
RECIPE = {'X':'X','Y columns':['Y'],'Grouping variables':[],'Model':'Straight line','Weighting':'Unweighted'}


class ParameterDialogTests(TkCase):
    def drive(self,action,*,frame=None,**recipe):
        from tramastat import AnalysisDialog
        seen={}
        def step():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,AnalysisDialog))
            if dialog.grab_current() is not dialog:
                self.root.after(20,step);return
            try:
                dialog.update_idletasks();action(dialog,seen)
            except Exception:seen['error']=traceback.format_exc()
            finally:dialog.result=None;dialog.cancel()
        self.root.deiconify();self.root.geometry('1000x700+0+0');ui_theme.configure(self.root)
        self.root.after(100,step)
        AnalysisDialog(self.root,FRAME.copy() if frame is None else frame.copy(),current=('Nonlinear regression',{**RECIPE,**recipe}),only='Nonlinear regression')
        self.root.withdraw();self.assertNotIn('error',seen,seen.get('error'));return seen

    def test_defaults_and_separate_confidence_page(self):
        def action(d,seen):
            self.assertIn('Confidence intervals',[d.fields.tab(p,'text') for p in d.fields.tabs()])
            self.assertEqual(d.controls[METHOD][1].get(),WALD)
            self.assertEqual(float(d.controls[LEVEL][1].get()),95)
            self.assertEqual(d.field_rows[METHOD][1].master,d.field_rows['Band'][1].master)
            self.assertTrue(d.validate());seen['options']=d.result[1]
        seen=self.drive(action)
        self.assertEqual(seen['options'][METHOD],WALD)

    def test_invalid_parameter_level_keeps_dialog_on_its_control(self):
        def action(d,seen):
            d.controls[LEVEL][1].set('100')
            with patch('tramastat.messagebox.showerror') as error:
                self.assertFalse(d.validate())
            self.assertIn('between 0 and 100',error.call_args.args[1])
            self.assertEqual(d.fields.select(),str(d.field_rows[LEVEL][1].master))
            self.assertEqual(d.focus_get(),d.field_rows[LEVEL][1])
            d.controls[LEVEL][1].set('90,5');self.assertTrue(d.validate())
            self.assertEqual(d.result[1][LEVEL],90.5)
        self.drive(action)

    def test_log_ic50_follows_the_model_and_the_saved_choice(self):
        self.use('it')

        def action(dialog, _):
            caption, _ = dialog.field_rows[REPORT_LOG_IC50]
            self.assertEqual(caption.cget('text'), 'Mostra log10(IC50)')
            log_ic50 = dialog.controls[REPORT_LOG_IC50][1]
            self.assertTrue(log_ic50.get())
            self.assertTrue(dialog.validate())
            self.assertIs(dialog.result[1][REPORT_LOG_IC50], True)
            dialog.controls['Model'][1].set('Straight line')
            self.assertFalse(caption.grid_info())
            self.assertTrue(dialog.validate())
            self.assertNotIn(REPORT_LOG_IC50, dialog.result[1])
            dialog.controls['Model'][1].set('Normalized inhibition (variable slope)')
            self.assertTrue(caption.grid_info())
            log_ic50.set(False)
            self.assertTrue(dialog.validate())
            self.assertNotIn(REPORT_LOG_IC50, dialog.result[1])

        self.drive(action, **{'Model': 'Normalized inhibition (variable slope)', REPORT_LOG_IC50: True})

    def test_parameter_profiles_and_diagnostics_are_never_fit_on_dialog_thread(self):
        def action(d,seen):
            d.controls[METHOD][1].set(PROFILE)
            d.controls['Runs test'][1].set(True)
            with patch('tramastat.analyse',side_effect=AssertionError('Must use worker')):
                self.assertTrue(d.validate())
            self.assertIsNone(d.processing_result)
            self.assertEqual(d.result[1][METHOD],PROFILE)
        self.drive(action)

    def test_curve_and_parameter_levels_are_independent(self):
        def action(d,seen):
            d.controls[METHOD][1].set(PROFILE);d.controls[LEVEL][1].set('90')
            d.controls['Band'][1].set('Confidence (mean)');d.controls['Confidence level (%)'][1].set('99')
            d.update();self.assertTrue(d.validate())
            self.assertEqual(d.result[1][LEVEL],90)
            self.assertEqual(d.result[1]['Confidence level (%)'],99)
        self.drive(action)

    def test_italian_caption_selection_and_error_preserve_canonical_recipe(self):
        self.use('it')
        def action(d,seen):
            self.assertEqual(d.field_rows[METHOD][0].cget('text'),'Intervalli dei parametri')
            self.assertIn('Profilo di verosimiglianza',d.field_rows[METHOD][1].cget('values'))
            d.controls[METHOD][1].set(PROFILE);d.controls[LEVEL][1].set('0')
            with patch('tramastat.messagebox.showerror') as error:self.assertFalse(d.validate())
            self.assertIn('strettamente compreso',error.call_args.args[1])
            self.assertIn('Livello di confidenza',error.call_args.args[1])
            d.controls[LEVEL][1].set('95');self.assertTrue(d.validate())
            self.assertEqual(d.result[1][METHOD],PROFILE)
        self.drive(action)
