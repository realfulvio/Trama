"""Actual graph clipboard transactions, guarded focus, history and worksheet independence."""
from copy import deepcopy
import tkinter as tk
import unittest
from unittest.mock import patch
import uuid

import pandas as pd

from tests import test_shape_context_app as base
from tests.test_shape_options import LINE, BOX
from analisi.graph_shapes import SHAPES
from analisi.i18n import tr
from analisi.presentation import apply_style
from analisi.shape_canvas import ShapeHistory
from analisi.shape_clipboard import dump_shape, load_shape


class DrawingClipboardAppTests(unittest.TestCase):
    setUpClass=classmethod(base.ShapeContextAppTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ShapeContextAppTests.tearDownClass.__func__)
    tearDown=base.ShapeContextAppTests.tearDown

    def setUp(self):
        base.ShapeContextAppTests.setUp(self)
        self.app.start_shape_mode('select')
        self.app.shape_controller.selected=LINE['id']
        self.assertTrue(hasattr(self.app,'shape_clipboard_action'),'Drawing clipboard UI is missing')

    def test_copy_preserves_project_and_cut_paste_are_undoable(self):
        before=deepcopy(self.run.style);canvas=self.app.graph_canvas;figure=self.run.result.figure
        self.assertTrue(self.app.shape_clipboard_action('copy'))
        self.assertEqual(load_shape(self.root.clipboard_get()),LINE)
        self.assertEqual(self.run.style,before);self.assertFalse(self.app.dirty)
        self.assertFalse(self.run.shape_history.changes)
        self.assertTrue(self.app.shape_clipboard_action('cut'))
        self.assertNotIn(SHAPES,self.run.style)
        self.app.apply_worksheet_history();self.assertEqual(self.run.style,before)
        self.assertTrue(self.app.shape_clipboard_action('paste'))
        self.assertEqual(len(self.run.style[SHAPES]),2)
        self.assertNotEqual(self.run.style[SHAPES][1]['id'],LINE['id'])
        self.app.apply_worksheet_history();self.assertEqual(self.run.style,before)
        self.app.apply_worksheet_history(redo=True);self.assertEqual(len(self.run.style[SHAPES]),2)
        self.assertIs(self.app.graph_canvas,canvas);self.assertIs(self.run.result.figure,figure)
        pd.testing.assert_frame_equal(self.app.tables['Canvas'].raw,self.frame)

    def test_clipboard_write_failure_never_cuts(self):
        errors=[];self.app.error=errors.append;before=deepcopy(self.run.style)
        with patch.object(self.app,'set_clipboard_text',side_effect=tk.TclError('clipboard busy')):
            self.assertFalse(self.app.shape_clipboard_action('cut'))
        self.assertEqual(self.run.style,before);self.assertTrue(errors)
        self.assertFalse(self.app.dirty);self.assertFalse(self.run.shape_history.changes)

    def test_invalid_foreign_and_out_of_domain_paste_are_atomic(self):
        errors=[];self.app.error=errors.append;before=deepcopy(self.run.style)
        for text in ('1\t2\n3\t4','{}',dump_shape({**LINE,'units':'data','points':[[-1.,1.],[2.,2.]]})):
            self.app.set_clipboard_text(text)
            self.run.result.figure.axes[0].set_xscale('log')
            self.assertFalse(self.app.shape_clipboard_action('paste'))
            self.assertEqual(self.run.style,before)
            self.assertEqual(len(self.run.result.figure.axes[0]._tramastat_shapes),1)
        self.assertEqual(len(errors),3);self.assertFalse(self.app.dirty)

    def test_limits_and_missing_selection_preserve_clipboard_and_graph(self):
        self.app.set_clipboard_text(dump_shape(BOX))
        self.app.shape_controller.selected=None
        errors=[];self.app.error=errors.append
        self.assertFalse(self.app.shape_clipboard_action('cut'))
        records=[{**deepcopy(LINE),'id':str(uuid.uuid4())} for _ in range(100)]
        apply_style(self.run.result.figure,{SHAPES:records});self.run.style={SHAPES:records}
        self.assertFalse(self.app.shape_clipboard_action('paste'))
        self.assertEqual(self.run.style[SHAPES],records)
        self.assertEqual(load_shape(self.root.clipboard_get()),BOX)
        self.assertEqual(len(errors),2)

    def test_failed_render_and_inspector_draft_preserve_confirmed_state(self):
        from types import SimpleNamespace
        errors=[];self.app.error=errors.append;before=deepcopy(self.run.style)
        self.app.set_clipboard_text(dump_shape(BOX))
        with patch('tramastat.render_shapes',side_effect=ValueError('render failed')):
            self.assertFalse(self.app.shape_clipboard_action('paste'))
        self.assertEqual(self.run.style,before);self.assertFalse(self.app.dirty)
        self.assertFalse(self.run.shape_history.changes);self.assertEqual(len(errors),1)
        original=self.app.inspector
        try:
            self.app.inspector=SimpleNamespace(has_draft=True)
            self.assertFalse(self.app.shape_clipboard_action('paste'))
            self.assertFalse(self.app.shape_clipboard_action('cut'))
        finally:self.app.inspector=original
        self.assertEqual(self.run.style,before)

    def test_stale_target_pan_zoom_pending_and_draft_cannot_edit_or_copy(self):
        before=deepcopy(self.run.style);self.app.set_clipboard_text('sentinel')
        self.app.graph_toolbar.pan()
        self.assertFalse(self.app.shape_clipboard_action('copy'))
        self.app.graph_toolbar.pan()
        self.app.pending=object()
        self.assertFalse(self.app.shape_clipboard_action('cut'))
        self.app.pending=None
        self.app.show('data','Canvas');self.root.update()
        self.assertFalse(self.app.shape_clipboard_action('paste',run=self.run))
        self.assertEqual(self.run.style,before);self.assertEqual(self.root.clipboard_get(),'sentinel')

    def test_context_copy_and_paste_controls_use_actual_clipboard(self):
        menu=self.app.make_shape_context_menu(self.run,LINE['id'])
        find=lambda key:base.ShapeContextAppTests.menu_item(self,menu,tr(key))
        menu.invoke(find('shape.clipboard.copy'))
        self.assertEqual(load_shape(self.root.clipboard_get()),LINE)
        menu.invoke(find('shape.clipboard.paste'))
        self.assertEqual(len(self.run.style[SHAPES]),2)

    def test_workspace_ribbon_dispatches_to_drawings_only_on_a_graph(self):
        self.assertTrue(hasattr(self.app,'copy_into_workspace'),'Ribbon copy does not dispatch drawing copies')
        self.app.copy_into_workspace()
        self.assertEqual(load_shape(self.root.clipboard_get()),LINE)
        self.app.paste_into_workspace()
        self.assertEqual(len(self.run.style[SHAPES]),2)
        self.app.show('data','Canvas');self.root.update()
        self.app.current_grid.select((0,1));self.app.copy_into_workspace()
        from analisi.grid_data import clipboard_rows, clipboard_decimal_mark
        self.assertEqual(clipboard_rows(self.root.clipboard_get()),[['2'+clipboard_decimal_mark()+'0']])

    def test_canvas_shortcuts_are_local_and_stop_mode_restores_bindings(self):
        widget=self.app.graph_canvas.get_tk_widget();widget.focus_force();self.root.update()
        widget.event_generate('<Control-c>');self.root.update()
        self.assertEqual(load_shape(self.root.clipboard_get()),LINE)
        widget.event_generate('<Control-v>');self.root.update()
        self.assertEqual(len(self.run.style[SHAPES]),2)
        self.app.start_shape_mode(None)
        self.assertFalse(widget.bind('<Control-c>'))
        self.assertFalse(widget.bind('<Control-v>'))
        self.app.show('data','Canvas');self.root.update()
        self.app.current_grid.select((0,1));self.app.copy_selection()
        from analisi.grid_data import clipboard_rows, clipboard_decimal_mark
        self.assertEqual(clipboard_rows(self.root.clipboard_get()),[['2'+clipboard_decimal_mark()+'0']])

    def test_copy_between_native_graphs_preserves_appearance_and_separate_history(self):
        from tramastat import Run
        from analisi.workbench import analyse
        self.app.shape_clipboard_action('copy')
        first=deepcopy(self.run.style)
        options=self.run.options.copy()
        self.app.tables['Canvas'].analyses.append(('Linear regression',options))
        other=Run('Linear regression','Canvas',options,
                  result=analyse('Linear regression',self.frame,options),slot=1,style={})
        self.app.runs.append(other)
        self.app.show('graph',1);self.root.update()
        self.assertTrue(self.app.shape_clipboard_action('paste'))
        pasted=deepcopy(other.style[SHAPES][0]);pasted['id']=LINE['id']
        self.assertEqual(pasted,LINE);self.assertEqual(self.run.style,first)
        self.app.apply_worksheet_history();self.assertNotIn(SHAPES,other.style)
        self.assertEqual(self.run.style,first)
