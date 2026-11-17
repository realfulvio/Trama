"""Canonical translated options and focus after correcting invalid summary data."""
import traceback
from unittest.mock import patch

import pandas as pd

from analisi import i18n
from analisi.summary_anova import METHOD
from tests.test_graph_i18n import TkCase


class SummaryDialogTests(TkCase):
    def test_italian_validation_hidden_fields_and_canonical_choices(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        language=i18n.active_language();self.addCleanup(i18n.set_language,language)
        i18n.set_language('it');seen={}
        frame=pd.DataFrame({'Group':['A','B','C'],'Mean':[2.,4.,6.],'SD':[1.,1.,1.],'N':[3,3,3]})
        def enter():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,AnalysisDialog))
            if dialog.grab_current() is not dialog:self.root.after(10,enter);return
            try:
                for name,value in {'Input':'Groups in rows','Group':'Group','Mean':'Mean','Dispersion':'SD',
                                   'Sample size':'N','Post-hoc':'Tukey'}.items():dialog.controls[name][1].set(value)
                dialog.controls['Confidence level (%)'][1].set('100')
                with patch('tramastat.messagebox.showerror') as report:
                    seen['invalid']=dialog.validate();seen['message']=report.call_args.args[1]
                seen['focus']=dialog.focus_get() is dialog.field_rows['Confidence level (%)'][1]
                dialog.controls['Confidence level (%)'][1].set('95')
                seen['valid']=dialog.validate();seen['options']=dialog.result[1]
                seen['display']=dialog.field_rows['Input'][1].get()
                seen['hidden']=not dialog.field_rows['Variables'][1].winfo_manager()
            except Exception:seen['error']=traceback.format_exc()
            finally:dialog.result=None;dialog.cancel()
        self.root.deiconify();self.root.after(80,enter);AnalysisDialog(self.root,frame,only=METHOD)
        self.assertNotIn('error',seen,seen.get('error'))
        self.assertFalse(seen['invalid']);self.assertIn('confidenza',seen['message']);self.assertTrue(seen['valid'])
        self.assertTrue(seen['focus']);self.assertTrue(seen['hidden'])
        self.assertEqual(seen['display'],'Gruppi nelle righe')
        self.assertEqual(seen['options']['Input'],'Groups in rows')
        self.assertEqual(seen['options']['Method'],'Ordinary')
        self.assertNotIn('Variables',seen['options'])

    def test_welch_keeps_typed_values_and_names_an_incompatible_posthoc(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        from analisi.summary_anova import GAMES, NOTE
        ui_theme.configure(self.root)
        language=i18n.active_language();self.addCleanup(i18n.set_language,language)
        i18n.set_language('it');seen={}
        frame=pd.DataFrame({'Group':['A','B','C'],'Mean':[10.,15.,18.],'SD':[2.,5.,3.],'N':[8,12,6]})
        def enter():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,AnalysisDialog))
            if dialog.grab_current() is not dialog:self.root.after(10,enter);return
            try:
                def walk(widget,found):
                    for child in widget.winfo_children():
                        if 'text' in child.keys():found.add(child.cget('text'))
                        walk(child,found)
                labels=set();walk(dialog,labels)
                seen['buttons']=('Esegui analisi' in labels, 'Annulla' in labels)
                seen['method']=dialog.field_rows['Method'][1].get()
                seen['note']=any(text==i18n.ui(NOTE) for text in labels)
                for name,value in {'Input':'Groups in rows','Group':'Group','Mean':'Mean','Dispersion':'SD',
                                   'Sample size':'N','Method':'Welch','Post-hoc':'Tukey'}.items():
                    dialog.controls[name][1].set(value)
                dialog.controls['Confidence level (%)'][1].set('90,5')
                with patch('tramastat.messagebox.showerror') as report:
                    seen['invalid']=dialog.validate();seen['message']=report.call_args.args[1]
                seen['kept']={name:dialog.controls[name][1].get() for name in
                              ('Group','Mean','Dispersion','Sample size','Method','Post-hoc')}
                seen['focus']=dialog.focus_get() is dialog.field_rows['Post-hoc'][1]
                dialog.controls['Post-hoc'][1].set(GAMES)
                seen['valid']=dialog.validate();seen['options']=dialog.result[1]
                dialog.update()
                def widget(text):
                    found=[]
                    def walk_one(widget):
                        for child in widget.winfo_children():
                            if 'text' in child.keys() and child.cget('text')==text:found.append(child)
                            walk_one(child)
                    walk_one(dialog)
                    return found[0]
                run, cancel = widget('Esegui analisi'), widget('Annulla')
                seen['reachable']=run.winfo_viewable() and cancel.winfo_viewable() and (
                    run.winfo_rooty()+run.winfo_height()<=dialog.winfo_screenheight())
            except Exception:seen['error']=traceback.format_exc()
            finally:dialog.result=None;dialog.cancel()
        self.root.deiconify();self.root.after(80,enter);AnalysisDialog(self.root,frame,only=METHOD)
        self.assertNotIn('error',seen,seen.get('error'))
        self.assertEqual(seen['method'],'Ordinaria')
        self.assertEqual(seen['buttons'],(True,True))
        self.assertTrue(seen['note'])
        self.assertFalse(seen['invalid'])
        self.assertIn('post hoc',seen['message'].lower())
        self.assertIn('Tukey',seen['message'])
        self.assertTrue(seen['focus'])
        self.assertTrue(seen['reachable'])
        self.assertEqual(seen['kept']['Method'],'Welch')
        self.assertEqual(seen['kept']['Post-hoc'],'Tukey')
        self.assertEqual(seen['kept']['Mean'],'Mean')
        self.assertTrue(seen['valid'])
        self.assertEqual(seen['options']['Method'],'Welch')
        self.assertEqual(seen['options']['Post-hoc'],GAMES)
        self.assertEqual(seen['options']['Confidence level (%)'],90.5)
