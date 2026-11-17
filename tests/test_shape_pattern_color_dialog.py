"""Actual editor/color controls keep appearance transactions and legacy defaults stable."""
from copy import deepcopy
import tkinter as tk
import unittest

from tests import test_shape_options_dialog as base
from tests.test_shape_options import BOX,LINE
from analisi.i18n import tr


class PatternColorDialogTests(unittest.TestCase):
    modal=base.ShapeOptionsDialogTests.modal
    use=base.ShapeOptionsDialogTests.use
    editor=base.ShapeOptionsDialogTests.editor
    setUpClass=classmethod(base.ShapeOptionsDialogTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ShapeOptionsDialogTests.tearDownClass.__func__)

    def test_default_is_absent_and_controls_follow_pattern_state(self):
        def action(editor):
            self.assertIn('hatch_color',editor.fields,'Independent pattern-color control is missing')
            self.assertTrue(editor.widgets['hatch_color'].instate(['disabled']))
            self.assertEqual(editor.read_record(),BOX)
            editor.fields['hatch'].set('cross');editor.update()
            self.assertTrue(editor.widgets['hatch_color'].instate(['!disabled']))
            self.assertNotIn('hatch_color',editor.read_record())
        self.editor(action,BOX)

    def test_invalid_color_reveals_appearance_and_focus_then_corrects_in_italian(self):
        self.use('it')
        def action(editor):
            self.assertIn('hatch_color',editor.fields,'Independent pattern-color control is missing')
            editor.fields['hatch_color'].set('invalid-color')
            editor.notebook.select(editor.pages['position']);editor.ok_button.focus_force();editor.update()
            editor.ok();editor.update()
            self.assertTrue(editor.winfo_exists());self.assertIsNone(editor.result)
            self.assertEqual(editor.notebook.select(),str(editor.pages['appearance']))
            self.assertIs(editor.focus_get(),editor.widgets['hatch_color'])
            self.assertEqual(editor.problem.cget('text'),tr('shape.error.hatch_color'))
            editor.fields['hatch_color'].set('#e54848');self.assertTrue(editor.validate())
            self.assertEqual(editor.result['hatch_color'],'#e54848')
        self.editor(action,{**BOX,'hatch':'cross'})

    def test_disabled_color_is_preserved_and_blank_active_field_returns_to_border(self):
        record={**BOX,'hatch':'cross','hatch_color':'#e54848'}
        def action(editor):
            self.assertIn('hatch_color',editor.fields,'Independent pattern-color control is missing')
            editor.fields['hatch'].set('none');editor.fields['hatch_color'].set('invalid');editor.update()
            self.assertEqual(editor.read_record()['hatch_color'],record['hatch_color'])
            editor.fields['hatch'].set('cross');editor.fields['hatch_color'].set('')
            result=editor.read_record();self.assertNotIn('hatch_color',result)
            self.assertEqual(result['stroke'],record['stroke']);self.assertEqual(result['fill'],record['fill'])
        self.editor(action,record)

    def test_line_controls_disabled_and_area_conversion_drops_area_color(self):
        def line(editor):
            self.assertIn('hatch_color',editor.fields,'Independent pattern-color control is missing')
            self.assertTrue(editor.widgets['hatch_color'].instate(['disabled']))
            self.assertEqual(editor.read_record(),LINE)
        self.editor(line,LINE)
        record={**BOX,'hatch':'cross','hatch_color':'#e54848'}
        def convert(editor):
            editor.fields['kind'].set('line');editor.update()
            result=editor.read_record();self.assertNotIn('hatch_color',result);self.assertNotIn('hatch',result)
        self.editor(convert,record)
