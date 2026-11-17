"""Pointer transactions, coordinate geometry, undo safety and export separation."""
from copy import deepcopy
from io import BytesIO
import unittest

import numpy as np
from matplotlib.backend_bases import MouseEvent, KeyEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from analisi.shape_canvas import ShapeCanvas, ShapeHistory
from analisi.graph_shapes import validate_shapes
from analisi.presentation import apply_style, graph_series
from tests.test_shape_options import LINE, BOX


class ShapeHistoryTests(unittest.TestCase):
    def test_undo_redo_branching_and_no_aliases(self):
        h=ShapeHistory();a=[deepcopy(LINE)];b=[deepcopy(BOX)]
        self.assertTrue(h.record([],a));self.assertTrue(h.record(a,b))
        self.assertEqual(h.apply(b),a);self.assertEqual(h.apply(a),[])
        self.assertEqual(h.apply([],redo=True),a)
        c=[{**LINE,'arrow_heads':'end'}];h.record(a,c)
        self.assertFalse(h.can_apply(redo=True));self.assertEqual(h.apply(c),a)
        a[0]['points'][0][0]=0.;self.assertEqual(h.apply([LINE],redo=True),c)

    def test_bounded_and_stale_history_never_overwrites_other_shapes(self):
        h=ShapeHistory(max_steps=2)
        states=[[],[LINE],[BOX],[{**LINE,'arrow_heads':'end'}]]
        for a,b in zip(states,states[1:]):h.record(a,b)
        self.assertEqual(len(h.changes),2)
        self.assertIsNone(h.apply([]));self.assertFalse(h.can_apply())


class ShapeCanvasTests(unittest.TestCase):
    def setUp(self):
        self.figure=Figure(figsize=(4,3),dpi=100);FigureCanvasAgg(self.figure)
        self.axes=self.figure.add_axes([.2,.2,.6,.6]);self.axes.plot([1,2,3],[2,4,5])
        self.axes.set(xlim=(0,10),ylim=(0,10));self.records=[];self.commits=[]
        self.figure.canvas.draw()
        self.editor=ShapeCanvas(self.figure.canvas,self.axes,records=lambda:deepcopy(self.records),
                                commit=self.commit,status=lambda text:None)
        self.addCleanup(self.editor.close)

    def commit(self,records):
        self.records=validate_shapes(records);self.commits.append(deepcopy(records))

    def event(self,name,point,**kwargs):
        pixel=self.axes.transAxes.transform(point)
        event=MouseEvent(name,self.figure.canvas,*pixel,button=1,**kwargs)
        self.figure.canvas.callbacks.process(name,event)

    def drag(self,start,end,**kwargs):
        self.event('button_press_event',start,**kwargs)
        self.event('motion_notify_event',end,**kwargs)
        self.event('button_release_event',end,**kwargs)

    def test_draw_then_cancel_and_zero_click_do_not_commit(self):
        self.editor.set_mode('rectangle');self.event('button_press_event',(.2,.2))
        self.event('motion_notify_event',(.7,.8))
        self.assertEqual(self.records,[]);self.assertEqual(len(self.axes._tramastat_shapes),1)
        self.editor.cancel();self.assertFalse(self.axes._tramastat_shapes)
        self.drag((.2,.2),(.2,.2));self.assertEqual(self.commits,[])
        self.drag((.2,.2),(1.2,.8));self.assertEqual(self.commits,[])

    def test_draw_all_kinds_and_ctrl_square_in_display_coordinates(self):
        for kind in ('line','arrow','rectangle','ellipse'):
            self.editor.set_mode(kind);self.drag((.2,.2),(.7,.8))
            self.assertEqual(len(self.records),len(self.commits))
        self.assertEqual([r['kind'] for r in self.records],['line','line','rectangle','ellipse'])
        self.assertEqual(self.records[1]['arrow_heads'],'end')
        self.editor.set_mode('ellipse');self.drag((.2,.2),(.5,.8),key='control')
        points=self.axes.transAxes.transform(self.records[-1]['points'])
        self.assertAlmostEqual(abs(points[1,0]-points[0,0]),abs(points[1,1]-points[0,1]))

    def test_invalid_release_discards_last_valid_preview_and_shift_reuses_tool(self):
        self.editor.set_mode('arrow');self.event('button_press_event',(.2,.2))
        self.event('motion_notify_event',(.6,.6))
        self.assertEqual(len(self.axes._tramastat_shapes),1)
        self.event('button_release_event',(1.3,.6))
        self.assertFalse(self.commits);self.assertFalse(self.axes._tramastat_shapes)
        self.drag((.2,.2),(.7,.7),key='shift')
        self.assertEqual(self.editor.mode,'arrow')

    def test_inverted_hollow_shape_selects_border_but_not_empty_interior(self):
        self.axes.invert_xaxis();self.axes.invert_yaxis()
        self.records=[{**BOX,'fill':None}];apply_style(self.figure,{'shapes':self.records})
        self.figure.canvas.draw();self.editor.set_mode('select')
        self.drag((.5,.5),(.5,.5));self.assertIsNone(self.editor.selected)
        self.drag((.15,.5),(.15,.5));self.assertEqual(self.editor.selected,BOX['id'])

    def test_move_keeps_data_artists_limits_and_view_and_one_commit(self):
        self.records=[deepcopy(BOX)];apply_style(self.figure,{'shapes':self.records});self.figure.canvas.draw()
        data=self.axes.lines[0];before=(self.axes.get_xlim(),self.axes.get_ylim(),self.axes.dataLim.get_points().copy())
        self.editor.set_mode('select');self.drag((.5,.5),(.6,.6))
        np.testing.assert_allclose(self.records[0]['points'],[[.25,.35],[.9,.8]],atol=.01)
        self.assertEqual(len(self.commits),1);self.assertIs(self.axes.lines[0],data)
        self.assertEqual((self.axes.get_xlim(),self.axes.get_ylim()),before[:2])
        np.testing.assert_array_equal(self.axes.dataLim.get_points(),before[2]);self.assertEqual(len(graph_series(self.axes)),1)

    def test_log_move_is_a_screen_translation_not_an_additive_data_offset(self):
        self.axes.set(xscale='log',xlim=(1,100),ylim=(0,10));self.figure.canvas.draw()
        r={**LINE,'units':'data','points':[[2.,3.],[20.,7.]]};self.records=[r]
        apply_style(self.figure,{'shapes':self.records});self.figure.canvas.draw();self.editor.set_mode('select')
        start=self.axes.transAxes.inverted().transform(self.axes.transData.transform([np.sqrt(40),5]))
        self.drag(start,start+np.array([.1,0]))
        got=np.array(self.records[0]['points']);expected=np.array(r['points'])*[100**.1,1]
        np.testing.assert_allclose(got,expected,rtol=.03)

    def test_resize_nudge_and_delete_are_transactional(self):
        self.records=[deepcopy(LINE)];apply_style(self.figure,{'shapes':self.records});self.figure.canvas.draw()
        self.editor.set_mode('select');self.drag((.8,.7),(.7,.75))
        np.testing.assert_allclose(self.records[0]['points'][1],[.7,.75],atol=.01)
        before=np.asarray(self.records[0]['points']);self.editor.key('right')
        after=np.asarray(self.records[0]['points']);width=self.axes.bbox.width
        np.testing.assert_allclose(after-before,[[1/width,0],[1/width,0]],atol=1e-10)
        self.editor.key('delete');self.assertEqual(self.records,[])

    def test_overlay_never_enters_export_and_callbacks_disconnect(self):
        self.records=[deepcopy(BOX)];apply_style(self.figure,{'shapes':self.records});self.figure.canvas.draw()
        from matplotlib import rc_context
        baseline=BytesIO()
        with rc_context({'svg.hashsalt':'shape-overlay'}):
            self.figure.savefig(baseline,format='svg',metadata={'Date':None})
        self.editor.set_mode('select');self.drag((.5,.5),(.5,.5));self.figure.canvas.draw()
        selected=BytesIO()
        with rc_context({'svg.hashsalt':'shape-overlay'}):
            self.figure.savefig(selected,format='svg',metadata={'Date':None})
        self.assertEqual(baseline.getvalue(),selected.getvalue())
        self.editor.close();self.drag((.5,.5),(.6,.6));self.assertEqual(self.commits,[])


class ShapeCanvasTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:cls.root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        cls.root.geometry('500x400')

    @classmethod
    def tearDownClass(cls):cls.root.destroy()

    def test_shape_keys_do_not_bubble_and_previous_bindings_are_restored(self):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        fig=Figure(figsize=(4,3));ax=fig.add_subplot();ax.plot([1,2],[3,4])
        canvas=FigureCanvasTkAgg(fig,master=self.root);widget=canvas.get_tk_widget();widget.pack()
        calls=[];prior=[]
        widget.bind('<Right>',lambda e:prior.append('prior'))
        self.root.bind('<Right>',lambda e:calls.append('root'))
        controller=ShapeCanvas(canvas,ax,records=lambda:[],commit=lambda r:None,status=lambda t:None)
        try:
            self.root.update();controller.set_mode('select');widget.focus_force();self.root.update()
            widget.event_generate('<Right>');self.root.update()
            self.assertEqual(calls,[]);self.assertEqual(prior,[])
            controller.set_mode(None);widget.event_generate('<Right>');self.root.update()
            self.assertEqual(prior,['prior']);self.assertEqual(calls,['root'])
        finally:
            controller.close();widget.destroy();self.root.unbind('<Right>')
