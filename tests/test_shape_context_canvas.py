"""Right-click selection is independent of draw mode and never commits a preview."""
from copy import deepcopy
import unittest
from matplotlib.backend_bases import MouseEvent
from analisi.shape_canvas import ShapeCanvas
from analisi.presentation import apply_style
from tests.test_shape_options import LINE, figure

class ShapeContextCanvasTests(unittest.TestCase):
    def test_right_click_selects_without_drawing_or_model_change(self):
        fig,ax=figure();apply_style(fig,{'shapes':[LINE]});fig.canvas.draw();calls=[];commits=[]
        editor=ShapeCanvas(fig.canvas,ax,records=lambda:[deepcopy(LINE)],commit=commits.append,status=lambda t:None,
                           context=lambda sid,event:calls.append(sid))
        self.addCleanup(editor.close)
        point=ax.transAxes.transform([.475,.475])
        editor.press(MouseEvent('button_press_event',fig.canvas,*point,button=3))
        self.assertEqual(calls,[LINE['id']]);self.assertEqual(editor.selected,LINE['id'])
        self.assertFalse(commits);self.assertIsNone(editor.gesture)
        editor.allowed=lambda:False
        editor.press(MouseEvent('button_press_event',fig.canvas,*point,button=3))
        self.assertEqual(len(calls),1)
