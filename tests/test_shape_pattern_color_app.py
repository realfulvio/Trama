"""Real graph color-menu transactions preserve independent border/fill and undo."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from tkinter import colorchooser

from tests import test_shape_context_app as base
from tests.test_shape_options import BOX
from analisi.graph_shapes import SHAPES
from analisi.i18n import tr
from analisi.presentation import apply_style
from analisi.shape_canvas import ShapeHistory


class PatternColorAppTests(unittest.TestCase):
    setUpClass=classmethod(base.ShapeContextAppTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ShapeContextAppTests.tearDownClass.__func__)
    tearDown=base.ShapeContextAppTests.tearDown

    def setUp(self):
        base.ShapeContextAppTests.setUp(self)
        self.record={**deepcopy(BOX),'hatch':'cross'}
        apply_style(self.run.result.figure,{SHAPES:[self.record]})
        self.app.commit_canvas_shapes(self.run,[self.record]);self.run.shape_history=ShapeHistory()
        self.app.dirty=False

    def test_picker_cancel_and_real_color_action_preserve_other_appearance_and_undo(self):
        before=deepcopy(self.run.style)
        with patch.object(colorchooser,'askcolor',return_value=(None,None)):
            self.assertFalse(self.app.choose_shape_context_color(self.run,BOX['id'],'hatch_color'))
        self.assertFalse(self.app.dirty);self.assertEqual(self.run.style,before)
        with patch.object(colorchooser,'askcolor',return_value=((229,72,72),'#e54848')):
            self.assertTrue(self.app.choose_shape_context_color(self.run,BOX['id'],'hatch_color'))
        self.assertEqual(self.run.style[SHAPES][0],{**self.record,'hatch_color':'#e54848'})
        self.assertEqual(len(self.run.result.figure.axes[0]._tramastat_shapes),1)
        self.app.apply_worksheet_history();self.assertEqual(self.run.style,before)
        self.app.apply_worksheet_history(redo=True)
        self.assertEqual(self.run.style[SHAPES][0]['hatch_color'],'#e54848')

    def test_actual_follow_border_command_removes_optional_key_then_is_a_noop(self):
        self.app.apply_shape_context(self.run,BOX['id'],'hatch_color','#e54848')
        menu=self.app.make_shape_context_menu(self.run,BOX['id'])
        index=base.ShapeContextAppTests.menu_item(self,menu,tr('shape.context.pattern_follow'))
        menu.invoke(index)
        self.assertEqual(self.run.style[SHAPES],[self.record])
        before=self.run.shape_history.position
        self.assertFalse(self.app.apply_shape_context(self.run,BOX['id'],'hatch_color',None))
        self.assertEqual(self.run.shape_history.position,before)

    def test_chooser_receives_rgb_even_for_matplotlib_colors_and_alpha_hex(self):
        self.app.apply_shape_context(self.run,BOX['id'],'stroke','tab:blue')
        self.app.apply_shape_context(self.run,BOX['id'],'hatch_color','#e5484880')
        before=deepcopy(self.run.style)
        for key,expected in [('stroke','#1f77b4'),('hatch_color','#e54848')]:
            with patch.object(colorchooser,'askcolor',return_value=(None,None)) as picker:
                self.assertFalse(self.app.choose_shape_context_color(self.run,BOX['id'],key))
                self.assertEqual(picker.call_args.kwargs['color'],expected)
        self.assertEqual(self.run.style,before)
