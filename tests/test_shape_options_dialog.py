"""Real editor controls for arrowheads and hatch fills, with legacy recipe stability."""
from copy import deepcopy
import tkinter as tk
import unittest

from analisi.graph_shape_dialog import ShapeEditor
from analisi.i18n import tr
from tests import test_graph_shape_dialog as base
from tests.test_shape_options import LINE, BOX


class ShapeOptionsDialogTests(unittest.TestCase):
    modal = base.ShapeDialogTests.modal
    use = base.ShapeDialogTests.use

    @classmethod
    def setUpClass(cls):
        try: cls.root=tk.Tk()
        except tk.TclError as error: raise unittest.SkipTest(str(error))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls): cls.root.destroy()

    def editor(self, action, record=LINE):
        _,axes=base.figure()
        return self.modal(lambda:ShapeEditor(self.root,axes,deepcopy(record)),action)

    def test_legacy_apply_adds_no_defaults_and_disables_irrelevant_fields(self):
        self.use('en')
        def action(editor):
            self.assertTrue(editor.widgets['arrow_heads'].instate(['!disabled']))
            for key in ('arrow_style','arrow_size','hatch','fill'):
                self.assertTrue(editor.widgets[key].instate(['disabled']),key)
            self.assertEqual(editor.read_record(),LINE)
        self.editor(action)

    def test_italian_arrow_choices_are_canonical_and_decimal_comma_is_accepted(self):
        self.use('it')
        def action(editor):
            editor.fields['arrow_heads'].set(tr('shape.option.both'))
            editor.fields['arrow_style'].set(tr('shape.option.filled'))
            editor.fields['arrow_size'].set('13,5')
            editor.update()
            self.assertTrue(editor.widgets['arrow_size'].instate(['!disabled']))
            record=editor.read_record()
            self.assertEqual(record['arrow_heads'],'both')
            self.assertEqual(record['arrow_style'],'filled')
            self.assertEqual(record['arrow_size'],13.5)
            self.assertIsNone(record['fill'])
        self.editor(action)

    def test_size_error_keeps_dialog_and_focus_then_correction_is_valid(self):
        self.use('en')
        def action(editor):
            editor.widgets['kind'].focus_force();editor.update()
            editor.fields['arrow_heads'].set('end');editor.fields['arrow_size'].set('0')
            editor.ok();editor.update()
            self.assertTrue(editor.winfo_exists());self.assertIsNone(editor.result)
            self.assertIs(editor.focus_get(),editor.widgets['arrow_size'])
            self.assertIn('3',editor.problem.cget('text'))
            editor.fields['arrow_size'].set('16')
            self.assertTrue(editor.validate());self.assertEqual(editor.result['arrow_size'],16)
        self.editor(action)

    def test_disabled_arrow_size_does_not_trap_legacy_user(self):
        self.use('en')
        def action(editor):
            editor.fields['arrow_heads'].set('end');editor.fields['arrow_size'].set('invalid')
            editor.fields['arrow_heads'].set('none');editor.update()
            self.assertEqual(editor.read_record(),LINE)
        self.editor(action)

    def test_hatch_is_canonical_and_arrows_are_disabled_on_boxes(self):
        self.use('it')
        def action(editor):
            self.assertTrue(editor.widgets['hatch'].instate(['!disabled']))
            self.assertTrue(editor.widgets['arrow_heads'].instate(['disabled']))
            editor.fields['hatch'].set(tr('shape.option.cross'))
            self.assertEqual(editor.read_record()['hatch'],'cross')
        self.editor(action,BOX)

    def test_changing_arrow_to_ellipse_drops_line_specific_options(self):
        self.use('en')
        arrow={**LINE,'arrow_heads':'both','arrow_style':'filled','arrow_size':18.}
        def action(editor):
            editor.fields['kind'].set('ellipse');editor.fields['hatch'].set('dots');editor.update()
            result=editor.read_record()
            self.assertEqual(result['kind'],'ellipse');self.assertEqual(result['hatch'],'dots')
            self.assertFalse(set(result)&{'arrow_heads','arrow_style','arrow_size'})
        self.editor(action,arrow)
