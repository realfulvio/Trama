"""Real Arrange menu transactions preserve source data, history and confirmed state."""
from copy import deepcopy
import unittest,uuid
import pandas as pd
from tests import test_shape_canvas_app as base
from tests.test_shape_options import BOX
from tests import test_shape_arrange as fixtures
from analisi.i18n import tr
from analisi.graph_shapes import SHAPES
from analisi.shape_canvas import ShapeHistory
from analisi.presentation import apply_style


class ArrangementAppTests(unittest.TestCase):
    setUpClass=classmethod(base.ShapeCanvasAppTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ShapeCanvasAppTests.tearDownClass.__func__)
    tearDown=base.ShapeCanvasAppTests.tearDown

    def setUp(self):
        base.ShapeCanvasAppTests.setUp(self)
        self.assertTrue(hasattr(self.app,'arrange_graph_shapes'),'Arrange drawing objects is not connected to the app')
        self.run=self.app.runs[0]
        self.records=[{**deepcopy(BOX),'id':str(uuid.UUID(int=i+1)),'points':points}
            for i,points in enumerate(deepcopy(list(fixtures.FIXTURE['points'].values())[:3]))]
        apply_style(self.run.result.figure,{SHAPES:self.records})
        self.app.commit_canvas_shapes(self.run,self.records);self.run.shape_history=ShapeHistory();self.app.dirty=False

    def drive(self,action,through_menu=False):
        from analisi.shape_arrange_dialog import ArrangeShapesDialog
        errors=[]
        def enter():
            found=[w for w in self.root.winfo_children() if isinstance(w,ArrangeShapesDialog)]
            if not found:self.root.after(20,enter);return
            dialog=found[-1]
            try:action(dialog)
            except Exception as error:errors.append(error)
            finally:
                if dialog.winfo_exists():dialog.cancel()
        self.root.after(50,enter)
        if through_menu:
            menu=self.app.menu
            top=next(i for i in range(menu.index('end')+1) if menu.type(i)=='cascade' and menu.entrycget(i,'label')==tr('menu.arrange'))
            popup=menu.nametowidget(menu.entrycget(top,'menu'))
            item=next(i for i in range(popup.index('end')+1) if popup.entrycget(i,'label')==tr('command.arrange_shapes'))
            popup.invoke(item)
        else:self.app.arrange_graph_shapes()
        if errors:raise errors[0]

    def test_real_arrange_menu_commits_one_undoable_transaction(self):
        def accept(dialog):dialog.fields['horizontal'].set('left');dialog.ok()
        self.drive(accept,through_menu=True)
        self.assertAlmostEqual(self.run.style[SHAPES][1]['points'][0][0],.1)
        self.assertEqual(len(self.run.shape_history.changes),1);self.assertTrue(self.app.dirty)
        self.app.apply_worksheet_history();self.assertEqual(self.run.style[SHAPES],self.records)
        self.app.apply_worksheet_history(redo=True)
        self.assertAlmostEqual(self.run.style[SHAPES][1]['points'][0][0],.1)
        pd.testing.assert_frame_equal(self.app.tables['Canvas'].raw,self.frame)

    def test_preview_cancel_and_confirmed_noop_preserve_dirty_and_history(self):
        before=deepcopy(self.run.style)
        def cancel(dialog):dialog.fields['horizontal'].set('right');self.assertTrue(dialog.preview());dialog.cancel()
        self.drive(cancel);self.assertEqual(self.run.style,before);self.assertFalse(self.app.dirty)
        self.drive(lambda dialog:dialog.ok())
        self.assertEqual(self.run.style,before);self.assertFalse(self.run.shape_history.changes)
        self.assertFalse(self.app.dirty)

    def test_non_graph_refusal_preserves_source_and_drawing_records(self):
        errors=[];self.app.error=errors.append
        self.app.show('data','Canvas');self.root.update()
        self.app.arrange_graph_shapes()
        self.assertTrue(errors);self.assertEqual(self.run.style[SHAPES],self.records)
        pd.testing.assert_frame_equal(self.app.tables['Canvas'].raw,self.frame)
