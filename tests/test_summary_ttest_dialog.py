"""Canonical translated options and focus after correcting invalid summary data."""
import traceback
from unittest.mock import patch

import pandas as pd

from analisi import i18n
from analisi.summary_ttest import METHOD
from tests.test_graph_i18n import TkCase


class SummaryTDialogTests(TkCase):
    def test_italian_validation_hidden_fields_and_canonical_choices(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        language=i18n.active_language();self.addCleanup(i18n.set_language,language)
        i18n.set_language('it');seen={}
        frame=pd.DataFrame({'Group':['A','B'],'Mean':[2.,4.],'SD':[1.,1.],'N':[3,3]})
        def enter():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,AnalysisDialog))
            if dialog.grab_current() is not dialog:self.root.after(10,enter);return
            try:
                for name,value in {'Input':'Groups in rows','Group':'Group','Mean':'Mean','Dispersion':'SD',
                                   'Sample size':'N','Design':'Student'}.items():dialog.controls[name][1].set(value)
                dialog.controls['Confidence level (%)'][1].set('100')
                with patch('tramastat.messagebox.showerror') as report:
                    seen['invalid']=dialog.validate();seen['message']=report.call_args.args[1]
                seen['focus']=dialog.focus_get() is dialog.field_rows['Confidence level (%)'][1]
                dialog.controls['Confidence level (%)'][1].set('95')
                seen['valid']=dialog.validate();seen['options']=dialog.result[1]
                seen['display']=dialog.field_rows['Input'][1].get()
                seen['hidden']=not dialog.field_rows['Variables'][1].winfo_manager()
                seen['numeric_errors']=[]
                for field,value,fragment in (('Null difference','abc','deve essere un numero'),
                                              ('Null difference','inf','deve essere finita'),
                                              ('Confidence level (%)','abc','deve essere un numero'),
                                              ('Confidence level (%)','nan','deve essere finito')):
                    dialog.controls[field][1].set(value)
                    with patch('tramastat.messagebox.showerror') as report:
                        valid=dialog.validate()
                    seen['numeric_errors'].append((valid,fragment in report.call_args.args[1],
                        dialog.focus_get() is dialog.field_rows[field][1]))
                    dialog.controls[field][1].set('0' if field=='Null difference' else '95')
            except Exception:seen['error']=traceback.format_exc()
            finally:dialog.result=None;dialog.cancel()
        self.root.deiconify();self.root.after(80,enter);AnalysisDialog(self.root,frame,only=METHOD)
        self.assertNotIn('error',seen,seen.get('error'))
        self.assertFalse(seen['invalid']);self.assertIn('confidenza',seen['message']);self.assertTrue(seen['valid'])
        self.assertTrue(seen['focus']);self.assertTrue(seen['hidden'])
        self.assertEqual(seen['numeric_errors'],[(False,True,True)]*4)
        self.assertEqual(seen['display'],'Gruppi nelle righe')
        self.assertEqual(seen['options']['Input'],'Groups in rows')
        self.assertNotIn('Variables',seen['options'])
        self.assertEqual(seen['options']['Design'],'Student')
        self.assertEqual(seen['options']['Null difference'],0.)
