"""Errors select the correct compact-editor page before focusing the field."""
import tkinter as tk
import unittest

from tests import test_shape_options_dialog as base


class ShapeEditorPageTests(unittest.TestCase):
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

    def test_coordinate_error_reveals_position_from_appearance(self):
        def action(editor):
            editor.notebook.select(editor.pages['appearance'])
            editor.ok_button.focus_force();editor.update()
            editor.fields['x2'].set('not a number');editor.ok_button.invoke();editor.update()
            self.assertTrue(editor.winfo_exists());self.assertIsNone(editor.result)
            self.assertEqual(editor.notebook.select(),str(editor.pages['position']))
            self.assertIs(editor.focus_get(),editor.widgets['x2'])
            editor.fields['x2'].set('.7');self.assertTrue(editor.validate())
        self.editor(action)

    def test_appearance_error_reveals_controls_from_position(self):
        self.use('it')
        def action(editor):
            editor.notebook.select(editor.pages['position'])
            editor.ok_button.focus_force();editor.update()
            editor.fields['width'].set('0');editor.ok_button.invoke();editor.update()
            self.assertTrue(editor.winfo_exists())
            self.assertEqual(editor.notebook.select(),str(editor.pages['appearance']))
            self.assertIs(editor.focus_get(),editor.widgets['width'])
            editor.fields['width'].set('1,5');self.assertTrue(editor.validate())
            self.assertLessEqual(editor.winfo_width(),1024)
            self.assertLessEqual(editor.winfo_height(),768)
            self.assertTrue(editor.ok_button.winfo_viewable())
        self.editor(action)
