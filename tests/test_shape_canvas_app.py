"""Native graph UI integration: shape transactions and per-graph undo are separate from data."""
from copy import deepcopy
import tkinter as tk
import unittest

import pandas as pd
from matplotlib.backend_bases import MouseEvent

from tramastat import App, Run
from analisi.data import Dataset
from analisi.graph_shapes import SHAPES
from analisi.workbench import analyse


class ShapeCanvasAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):cls.root.destroy()

    def setUp(self):
        # A fresh actual App each time; no mock rendering or replacement controller.
        self.root.deiconify()
        self.app=App(self.root)
        self.app.error=lambda e:self.fail(str(e))
        self.frame=pd.DataFrame({'X':[1.,2,3,4,5],'Y':[2.,4.1,5.9,8.,10.1]})
        opts={'X':'X','Y':'Y'}
        self.app._add_tables({'Canvas':self.frame.copy()})
        self.app.tables['Canvas'].analyses=[('Linear regression',opts)]
        self.app.runs=[Run('Linear regression','Canvas',opts,result=analyse('Linear regression',self.frame,opts),slot=0,style={})]
        self.app.show('graph',0);self.root.update();self.app.graph_canvas.draw();self.app.dirty=False

    def tearDown(self):
        if getattr(self.app,'shape_controller',None) is not None:self.app.shape_controller.close()
        self.root.update_idletasks()
        self.app.worker.shutdown(wait=True)
        for child in self.root.winfo_children():child.destroy()
        self.root.withdraw()

    def event(self,name,point):
        canvas=self.app.graph_canvas;axes=canvas.figure.axes[0];pixel=axes.transAxes.transform(point)
        canvas.callbacks.process(name,MouseEvent(name,canvas,*pixel,button=1));self.root.update()

    def test_draw_undo_redo_and_view_switch_preserve_data(self):
        self.assertTrue(self.app.start_shape_mode('rectangle'))
        self.event('button_press_event',(.2,.2));self.event('motion_notify_event',(.7,.7))
        self.assertNotIn(SHAPES,self.app.runs[0].style)
        self.event('button_release_event',(.7,.7))
        self.assertEqual(len(self.app.runs[0].style[SHAPES]),1)
        self.assertTrue(self.app.dirty)
        pd.testing.assert_frame_equal(self.app.tables['Canvas'].raw,self.frame)
        self.app.apply_worksheet_history();self.root.update()
        self.assertNotIn(SHAPES,self.app.runs[0].style)
        self.app.apply_worksheet_history(redo=True);self.root.update()
        self.assertEqual(len(self.app.runs[0].style[SHAPES]),1)
        self.app.show('data','Canvas');self.app.show('graph',0);self.root.update()
        self.app.apply_worksheet_history();self.root.update()
        self.assertNotIn(SHAPES,self.app.runs[0].style)
        pd.testing.assert_frame_equal(self.app.tables['Canvas'].raw,self.frame)

    def test_leaving_sheet_cancels_preview_and_releases_pointer(self):
        self.app.start_shape_mode('arrow')
        self.event('button_press_event',(.2,.2));self.event('motion_notify_event',(.7,.7))
        figure=self.app.runs[0].result.figure
        self.assertEqual(len(figure.axes[0]._tramastat_shapes),1)
        self.app.show('data','Canvas');self.root.update()
        self.assertFalse(figure.axes[0]._tramastat_shapes)
        self.assertNotIn(SHAPES,self.app.runs[0].style)
        self.assertFalse(self.app.dirty)
        self.assertIsNone(self.root.grab_current())

    def test_navigation_and_drawing_are_mutually_exclusive(self):
        self.app.graph_toolbar.pan()
        self.assertTrue(self.app.graph_toolbar.mode)
        self.assertTrue(self.app.start_shape_mode('line'))
        self.assertFalse(self.app.graph_toolbar.mode)
        self.event('button_press_event',(.2,.2));self.event('motion_notify_event',(.7,.7))
        self.app.graph_toolbar.zoom()
        self.event('button_release_event',(.7,.7))
        self.assertNotIn(SHAPES,self.app.runs[0].style)
        self.assertIsNone(self.root.grab_current())

    def test_shape_undo_keeps_other_style_changes_and_other_graph_history(self):
        first=self.app.runs[0]
        self.app.start_shape_mode('line')
        self.event('button_press_event',(.2,.2));self.event('button_release_event',(.6,.6))
        style=deepcopy(first.style);style['title']='A separate title edit'
        self.app.commit_graph_style(first,style)
        self.app.apply_worksheet_history()
        self.assertNotIn(SHAPES,first.style)
        self.assertEqual(first.style['title'],'A separate title edit')
        self.app.apply_worksheet_history(redo=True)
        self.app.runs.append(Run('Linear regression','Canvas',first.options.copy(),
            result=analyse('Linear regression',self.frame,first.options),slot=1,style={}))
        self.app.tables['Canvas'].analyses.append(('Linear regression',first.options.copy()))
        self.app.show('graph',1);self.root.update()
        self.app.start_shape_mode('arrow')
        self.event('button_press_event',(.2,.2));self.event('button_release_event',(.6,.6))
        self.app.apply_worksheet_history()
        self.assertNotIn(SHAPES,self.app.runs[1].style)
        self.assertEqual(len(first.style[SHAPES]),1)
