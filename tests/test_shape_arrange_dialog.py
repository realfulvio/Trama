"""Real modal controls protect confirmed geometry and report selection errors in place."""
from copy import deepcopy
import importlib.util
import tkinter as tk
import unittest
import numpy as np
from analisi.i18n import active_language,set_language,tr
from analisi.shape_canvas import render_shapes
from tests import test_shape_arrange as fixtures

if importlib.util.find_spec('analisi.shape_arrange_dialog') is not None:
    from analisi.shape_arrange_dialog import ArrangeShapesDialog
else:ArrangeShapesDialog=None


class ArrangementDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):cls.root.destroy()

    def setUp(self):
        self.assertIsNotNone(ArrangeShapesDialog,'The multi-object arrangement dialog is missing')
        fixture=fixtures.ArrangementTests();fixture.setUp()
        self.axes,self.figure,self.records,self.ids=fixture.ax,fixture.fig,fixture.records[:3],fixture.ids
        previous=active_language();self.addCleanup(set_language,previous);set_language('en')

    def modal(self,action,preview=None,records=None):
        seen={}
        def drive():
            found=[w for w in self.root.winfo_children() if isinstance(w,ArrangeShapesDialog)]
            if not found:self.root.after(20,drive);return
            dialog=found[-1];dialog.update()
            try:action(dialog)
            except Exception as error:seen['error']=error
            finally:
                if dialog.winfo_exists():dialog.cancel()
        self.root.after(50,drive)
        dialog=ArrangeShapesDialog(self.root,self.axes,records or self.records,preview=preview)
        if 'error' in seen:raise seen['error']
        return dialog

    def test_italian_combobox_and_direct_labels_resolve_to_geometry_only(self):
        set_language('it')
        def action(dialog):
            self.assertEqual(set(dialog.tree.selection()),set(self.ids))
            dialog.fields['horizontal'].set(tr('arrange.option.left'))
            dialog.widgets['vertical'].current(1)
            result=dialog.read_candidate()
            np.testing.assert_allclose([r['points'] for r in result],
                [[[.1,.7],[.2,.9]],[[.1,.7],[.3,.9]],[[.1,.8],[.2,.9]]],atol=1e-12)
            self.assertEqual(dialog.fields['vertical'].get(),'top')
            self.assertEqual(dialog.confirmed,self.records)
        self.modal(action)

    def test_invalid_selection_keeps_modal_and_focus_then_corrects(self):
        def action(dialog):
            dialog.tree.selection_remove(*dialog.tree.selection())
            dialog.apply_button.focus_force();dialog.update();dialog.ok();dialog.update()
            self.assertTrue(dialog.winfo_exists());self.assertIsNone(dialog.result)
            self.assertIs(dialog.focus_get(),dialog.tree)
            self.assertTrue(dialog.message.cget('text'))
            dialog.tree.selection_set(self.ids);dialog.fields['horizontal'].set('right')
            self.assertTrue(dialog.validate());self.assertIsNotNone(dialog.result)
        self.modal(action)

    def test_preview_is_from_initial_snapshot_and_cancel_restores_real_artists(self):
        render_shapes(self.axes,self.records)
        def preview(records):
            render_shapes(self.axes,self.records if records is None else records);self.figure.canvas.draw()
        def action(dialog):
            dialog.fields['horizontal'].set('left');self.assertTrue(dialog.preview())
            first=deepcopy(dialog.shown);dialog.preview();self.assertEqual(dialog.shown,first)
            self.assertEqual(self.records,dialog.confirmed)
            self.assertAlmostEqual(self.axes._tramastat_shapes[1].get_x(),.1)
            dialog.cancel()
        dialog=self.modal(action,preview=preview)
        self.assertIsNone(dialog.result)
        self.assertAlmostEqual(self.axes._tramastat_shapes[1].get_x(),.4)

    def test_cancel_discards_a_validated_but_unconfirmed_candidate(self):
        def action(dialog):
            dialog.fields['horizontal'].set('left');self.assertTrue(dialog.preview())
            self.assertTrue(dialog.validate());self.assertIsNotNone(dialog.result)
            dialog.cancel()
        dialog=self.modal(action)
        self.assertIsNone(dialog.result)

    def test_spacing_error_focuses_mode_and_successful_apply_has_fixed_visible_buttons(self):
        crowded=deepcopy(self.records)
        for i in range(3):crowded[i]['points']=[[.1+i*.05,.2],[.6+i*.05,.4]]
        def action(dialog):
            dialog.fields['horizontal'].set('distribute')
            dialog.apply_button.focus_force();dialog.update();dialog.ok();dialog.update()
            self.assertIs(dialog.focus_get(),dialog.widgets['horizontal'])
            self.assertTrue(dialog.winfo_exists());self.assertIsNone(dialog.result)
            dialog.fields['horizontal'].set('left');dialog.update()
            self.assertTrue(dialog.apply_button.winfo_viewable());self.assertTrue(dialog.cancel_button.winfo_viewable())
            self.assertLess(dialog.winfo_reqheight(),700)
            dialog.ok()
        dialog=self.modal(action,records=crowded)
        self.assertIsNotNone(dialog.result)
        self.assertEqual(dialog.confirmed,crowded)
