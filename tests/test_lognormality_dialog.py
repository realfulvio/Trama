"""Translated canonical distribution selectors on real Tk controls."""
import traceback
from unittest.mock import patch
import numpy as np
import pandas as pd
from analisi import i18n
from tests.test_graph_i18n import TkCase


class LognormalityDialog(TkCase):
    def test_italian_canonical_values_and_invalid_qq_field(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        original=i18n.active_language();self.addCleanup(i18n.set_language,original)
        i18n.set_language('it')
        data=pd.DataFrame({'A':np.arange(12.),'B':np.exp(np.arange(12.)/5)})
        seen={}
        def enter():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,AnalysisDialog))
            if dialog.grab_current() is not dialog:self.root.after(10,enter);return
            try:
                box=dialog.controls['Variables'][1]
                box.selection_set(0,'end')
                dialog.controls['Distribution'][1].set('Both')
                dialog.controls['Compare distributions'][1].set(True)
                dialog.controls['Q–Q plot'][1].set(True)
                dialog.controls['Q–Q variable'][1].set('A')
                dialog.update()
                seen['display']=dialog.field_rows['Distribution'][1].get()
                with patch('tramastat.messagebox.showerror') as report:
                    seen['invalid']=dialog.validate()
                    seen['message']=report.call_args.args[1]
                dialog.controls['Q–Q variable'][1].set('B')
                seen['valid']=dialog.validate()
                seen['options']=dialog.result[1]
            except Exception:seen['error']=traceback.format_exc()
            finally:dialog.result=None;dialog.cancel()
        self.root.deiconify();self.root.after(80,enter)
        AnalysisDialog(self.root,data,only='Normality tests')
        self.assertNotIn('error',seen,seen.get('error'))
        self.assertEqual(seen['display'],'Entrambe')
        self.assertFalse(seen['invalid'])
        self.assertIn('positivi',seen['message'])
        self.assertTrue(seen['valid'])
        self.assertEqual(seen['options']['Distribution'],'Both')
        self.assertTrue(seen['options']['Compare distributions'])
