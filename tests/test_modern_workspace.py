"""Modern worksheet integration: real figures, isolated drafts, edits and persistence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import tramastat
from analisi import ui_theme
from analisi.i18n import set_language
from analisi.theme_preferences import save_theme


class ModernWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'preferences.json'
        save_theme(self.path, 'modern')
        self.root = tk.Tk()
        with patch.object(tramastat, 'config_path', return_value=self.path):
            self.app = tramastat.App(self.root)
        self.root.geometry('1550x900+0+0')
        self.errors = []
        self.app.error = lambda message: self.errors.append(str(message))
        self.frame = pd.DataFrame({'X':[1.,2.,3.,4.,5.], 'Y':[2.1,4.2,5.8,8.1,10.2]})
        self.frame.attrs['table_format'] = 'XY'
        self.app._add_tables({'Experiment':self.frame})
        self.run = tramastat.Run('Linear regression','Experiment',{'X':'X','Y':'Y'})
        self.app.add_result(self.run, self.app.compute(self.run, self.frame))
        self.app.show('data','Experiment')
        self.root.update()

    def tearDown(self):
        self.wait()
        self.app._clear('')
        self.app.worker.shutdown(wait=True)
        self.root.destroy()
        self.tmp.cleanup()
        ui_theme.select_theme('standard')
        set_language('en')

    def wait(self):
        until = time.monotonic()+10
        while self.app.pending is not None and time.monotonic()<until:
            self.root.update()
            time.sleep(.02)
        self.root.update()
        self.assertIsNone(self.app.pending)

    def test_live_preview_is_a_copy_and_apply_cancel_keep_source_size(self):
        ws=self.app.modern_workspace
        self.assertIsNotNone(ws.canvas, self.errors)
        self.assertIsNot(ws.figure, self.run.result.figure)
        original=self.run.result.figure
        size=original.get_size_inches().copy()
        dpi=original.dpi
        xlabel=original.axes[0].get_xlabel()
        inspector=ws.inspector
        inspector.vars['xlabel'].set('Preview only')
        inspector._now('xlabel')
        self.root.update()
        self.assertEqual(ws.figure.axes[0].get_xlabel(),'Preview only')
        self.assertEqual(original.axes[0].get_xlabel(),xlabel)
        inspector.discard()
        self.assertEqual(ws.figure.axes[0].get_xlabel(),xlabel)
        inspector.vars['xlabel'].set('Confirmed axis')
        inspector._now('xlabel')
        self.assertTrue(inspector.apply())
        self.assertEqual(original.axes[0].get_xlabel(),'Confirmed axis')
        self.assertEqual(self.run.style['xlabel'],'Confirmed axis')
        self.assertEqual(self.app.tables['Experiment'].graph_styles[self.run.slot]['xlabel'],'Confirmed axis')
        self.root.geometry('1000x690+0+0')
        self.root.update()
        np.testing.assert_array_equal(original.get_size_inches(),size)
        self.assertEqual(original.dpi,dpi)
        self.assertFalse(self.errors)

    def test_edit_recalculates_preview_without_replacing_grid_or_stale_output(self):
        ws=self.app.modern_workspace
        old_result=self.run.result
        self.app.current_grid.select_block(1,1,2,1)
        self.app.edit_cell(0,1,'9')
        grid=self.app.current_grid
        self.wait()
        self.assertIsNot(self.run.result,old_result)
        self.assertIs(self.app.current_grid,grid)
        ws=self.app.modern_workspace
        self.assertIsNotNone(ws.canvas,self.errors)
        self.assertEqual(ws._result_identity,(id(self.run),id(self.run.result)))
        self.assertEqual(grid.anchor,(1,1))
        self.app.apply_worksheet_history()
        self.wait()
        self.assertEqual(self.app.tables['Experiment'].raw.iloc[0,1],2.1)
        self.assertFalse(self.errors)

    def test_hide_show_and_navigation_discard_draft(self):
        ws=self.app.modern_workspace
        size=self.run.result.figure.get_size_inches().copy()
        ws.inspector.vars['xlabel'].set('Not saved')
        ws.inspector._now('xlabel')
        ws.preview_wanted.set(False)
        ws.toggle_preview()
        self.root.update()
        self.assertIsNone(ws.canvas)
        self.assertIsNone(self.app.inspector)
        self.assertNotEqual(self.run.result.figure.axes[0].get_xlabel(),'Not saved')
        ws.preview_wanted.set(True)
        ws.toggle_preview()
        self.root.update()
        self.assertIsNotNone(ws.canvas)
        self.app.open_graph_view(0)
        self.root.update()
        self.assertIsNone(self.app.modern_workspace)
        self.app.show('data','Experiment')
        self.root.update()
        self.assertIsNotNone(self.app.modern_workspace.canvas)
        self.assertFalse(self.errors)

    def test_save_settles_draft_and_reopen_has_the_confirmed_style(self):
        ws=self.app.modern_workspace
        ws.inspector.vars['xlabel'].set('Stored axis')
        ws.inspector._now('xlabel')
        self.app.path=Path(self.tmp.name)/'roundtrip.alab'
        with patch.object(tramastat.messagebox,'askyesnocancel',return_value=True):
            self.assertTrue(self.app.save())
        self.assertFalse(ws.inspector.has_draft)
        payload=json.loads(self.app.path.read_text())
        self.assertNotIn('theme',payload)
        self.assertIn('Stored axis',json.dumps(payload))
        self.app.open_document(str(self.app.path))
        self.root.update()
        # Projects intentionally reopen with deferred calculations.
        self.app.show('data','Experiment')
        self.app.recalculate(0)
        self.wait()
        self.assertEqual(self.app.runs[0].style['xlabel'],'Stored axis')
        self.assertEqual(self.app.modern_workspace.figure.axes[0].get_xlabel(),'Stored axis')
        self.assertFalse(self.errors)

    def test_failed_edit_never_keeps_a_misleading_preview(self):
        # All X become identical: the existing regression fails, so no old curve remains visible.
        for row in range(len(self.frame)):
            self.app.tables['Experiment'].raw.iloc[row,0] = 1.
        self.app.invalidate()
        self.wait()
        self.assertIsNone(self.run.result)
        self.assertIsNone(self.app.modern_workspace.canvas)
        self.assertIsNone(self.app.inspector)

    def test_editing_and_resizing_do_not_recreate_preview_on_selection(self):
        ws=self.app.modern_workspace
        canvas=ws.canvas
        original=self.run.result.figure
        limits=(original.axes[0].get_xlim(),original.axes[0].get_ylim())
        for row in range(4):
            self.app.current_grid.select_block(row,0,row,1)
            self.app.current_grid.draw()
            self.root.update()
        self.assertIs(ws.canvas,canvas)
        self.assertEqual((original.axes[0].get_xlim(),original.axes[0].get_ylim()),limits)
        ws.sidebar_wanted.set(True)
        ws.toggle_sidebar()
        self.root.update()
        self.assertIn(str(ws.sidebar),ws.body.panes())
        ws.inspector.vars['xlabel'].set('Draft while switching')
        ws.inspector._now('xlabel')
        second=tramastat.Run('Linear regression','Experiment',{'X':'X','Y':'Y'})
        self.app.add_result(second,self.app.compute(second,self.frame),reveal=False)
        ws.refresh()
        ws.choice.current(0)
        ws._chosen()
        self.assertNotEqual(original.axes[0].get_xlabel(),'Draft while switching')
        self.assertIsNotNone(ws.canvas)

    def test_retained_normalization_result_is_visibly_marked_after_failed_edit(self):
        frame = pd.DataFrame({'Y':[1.,2.,3.]})
        self.app._add_tables({'Normalize':frame})
        run=tramastat.Run('Normalize to references','Normalize',{'Variables':['Y'],'Graph results':True})
        self.app.add_result(run,self.app.compute(run,frame))
        self.app.show('data','Normalize')
        self.root.update()
        previous=run.result
        self.app.tables['Normalize'].raw.loc[:,'Y']=1.
        self.app.invalidate()
        self.wait()
        self.assertIs(run.result,previous)
        self.assertTrue(run.calculation_error)
        workspace=self.app.modern_workspace
        self.assertIsNotNone(workspace.canvas)
        self.assertTrue(workspace.warning.winfo_manager())
        self.assertEqual(workspace.warning.cget('text'),self.app.stale_calculation_note(('graph',1)))
        self.app.edit_cell(2,0,'3')
        self.wait()
        self.assertIsNone(run.calculation_error)
        self.assertFalse(self.app.modern_workspace.warning.winfo_manager())

    def test_qq_styles_survive_preview_copy_and_do_not_mutate_source(self):
        from analisi.qq_panels import PANEL_KEY, POINTS_ATTR, REFERENCE_ATTR, panel_axes
        frame=pd.DataFrame({'Value':[1.,1.5,2.5,4.,7.,11.,19.,30.]})
        self.app._add_tables({'Distributions':frame})
        run=tramastat.Run('Normality tests','Distributions',{'Variables':['Value'],'Distribution':'Both',
                             'Q–Q plot':True,'Q–Q variable':'Value','Q–Q reference line':True})
        run.style={PANEL_KEY:{'normal':{'points':{'color':'#007f79','size':8.}},
                             'lognormal':{'reference_line':{'color':'#ef806d','style':'--'}}}}
        self.app.add_result(run,self.app.compute(run,frame))
        self.app.show('data','Distributions');self.root.update()
        workspace=self.app.modern_workspace
        self.assertIsNotNone(workspace.canvas,self.errors)
        original=panel_axes(run.result.figure);preview=panel_axes(workspace.figure)
        self.assertEqual(set(preview),{'normal','lognormal'})
        for key in preview:
            points=getattr(preview[key],POINTS_ATTR);source=getattr(original[key],POINTS_ATTR)
            self.assertIsNot(points,source)
            np.testing.assert_array_equal(points.get_sizes(),source.get_sizes())
            np.testing.assert_array_equal(points.get_facecolors(),source.get_facecolors())
            np.testing.assert_array_equal(points.get_offsets(),source.get_offsets())
        line=getattr(preview['lognormal'],REFERENCE_ATTR)
        self.assertEqual(line.get_linestyle(),'--')
        line.set_visible(False)
        self.assertTrue(getattr(original['lognormal'],REFERENCE_ATTR).get_visible())
        self.assertFalse(self.errors)
