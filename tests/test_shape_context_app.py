"""Real application menu operations preserve graph/data transactions and undo safety."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import pandas as pd

from tests import test_shape_canvas_app as base
from tests.test_shape_options import LINE
from analisi.i18n import tr
from analisi.presentation import apply_style
from analisi.shape_canvas import ShapeHistory
from analisi.graph_shapes import SHAPES


class ShapeContextAppTests(unittest.TestCase):
    setUpClass=classmethod(base.ShapeCanvasAppTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ShapeCanvasAppTests.tearDownClass.__func__)
    tearDown=base.ShapeCanvasAppTests.tearDown

    def setUp(self):
        base.ShapeCanvasAppTests.setUp(self)
        self.run=self.app.runs[0]
        apply_style(self.run.result.figure,{SHAPES:[LINE]})
        self.app.commit_canvas_shapes(self.run,[deepcopy(LINE)])
        self.run.shape_history=ShapeHistory();self.app.dirty=False

    def menu_item(self,menu,label):
        return next(i for i in range(menu.index('end')+1) if menu.type(i)!='separator' and menu.entrycget(i,'label')==label)

    def test_actual_menu_change_is_undoable_without_recalculation_or_data_mutation(self):
        canvas=self.app.graph_canvas;figure=self.run.result.figure
        menu=self.app.make_shape_context_menu(self.run,LINE['id'])
        self.assertFalse(self.app.dirty)
        item=self.menu_item(menu,tr('shape.context.width_line'))
        widths=menu.nametowidget(menu.entrycget(item,'menu'));widths.invoke(5)
        self.assertEqual(self.run.style[SHAPES][0]['width'],3.)
        self.assertIs(self.app.graph_canvas,canvas);self.assertIs(self.run.result.figure,figure)
        self.assertTrue(self.app.dirty)
        self.app.apply_worksheet_history();self.assertEqual(self.run.style[SHAPES],[LINE])
        pd.testing.assert_frame_equal(self.app.tables['Canvas'].raw,self.frame)

    def test_color_cancel_noop_and_invalid_candidate_preserve_history(self):
        before=deepcopy(self.run.style)
        with patch('tramastat.colorchooser.askcolor',return_value=(None,None)):
            self.assertFalse(self.app.choose_shape_context_color(self.run,LINE['id'],'stroke'))
        self.assertFalse(self.app.apply_shape_context(self.run,LINE['id'],'width',LINE['width']))
        errors=[];self.app.error=errors.append
        self.assertFalse(self.app.apply_shape_context(self.run,LINE['id'],'width',0))
        self.assertTrue(errors);self.assertEqual(self.run.style,before)
        self.assertFalse(self.run.shape_history.changes);self.assertFalse(self.app.dirty)

    def test_duplicate_identity_and_stale_graph_callback(self):
        menu=self.app.make_shape_context_menu(self.run,LINE['id'])
        menu.invoke(self.menu_item(menu,tr('shape.context.duplicate')))
        records=self.run.style[SHAPES];self.assertEqual(len(records),2)
        self.assertNotEqual(records[0]['id'],records[1]['id'])
        self.assertEqual(self.app.shape_controller.selected,records[1]['id'])
        before=deepcopy(self.run.style)
        self.app.show('data','Canvas');self.root.update()
        self.assertFalse(self.app.apply_shape_context(self.run,LINE['id'],'remove'))
        self.assertEqual(self.run.style,before)
