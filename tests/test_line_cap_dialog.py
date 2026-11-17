"""Translated cap choices and disabled/default compatibility in the actual shape editor."""
import tkinter as tk
import unittest

from analisi.i18n import tr
from analisi.graph_shape_dialog import describe_shape
from tests import test_shape_options_dialog as base
from tests.test_shape_options import LINE


class LineCapDialogTests(unittest.TestCase):
    modal=base.ShapeOptionsDialogTests.modal
    use=base.ShapeOptionsDialogTests.use
    editor=base.ShapeOptionsDialogTests.editor

    @classmethod
    def setUpClass(cls):
        try:cls.root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):cls.root.destroy()

    def test_canonical_and_translated_cap_choices_in_both_languages(self):
        for language in ('en','it'):
            self.use(language)
            for label in ('cap',tr('shape.option.cap')):
                with self.subTest(language=language,label=label):
                    def choose(editor):
                        editor.fields['arrow_heads'].set('both')
                        editor.fields['arrow_style'].set(label)
                        editor.fields['arrow_size'].set('13,5')
                        self.assertTrue(editor.validate())
                        self.assertEqual(editor.result['arrow_style'],'cap')
                        self.assertEqual(editor.result['arrow_size'],13.5)
                        self.assertEqual(describe_shape(editor.result)[0],tr('shape.option.capped_line'))
                    self.editor(choose)

    def test_existing_cap_can_be_disabled_without_losing_saved_preference(self):
        record={**LINE,'arrow_heads':'both','arrow_style':'cap','arrow_size':18.}
        def disable(editor):
            editor.fields['arrow_heads'].set('none')
            editor.fields['arrow_style'].set('invalid disabled text');editor.sync_kind()
            self.assertTrue(editor.validate())
            self.assertEqual(editor.result['arrow_style'],'cap')
            self.assertEqual(editor.result['arrow_heads'],'none')
        self.editor(disable,record)
