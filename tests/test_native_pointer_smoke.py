"""OS pointer coordinates must use Tk logical pixels even on high-DPI canvases."""
import importlib.util
import unittest
if importlib.util.find_spec('analisi.native_pointer_smoke'):
    from analisi.native_pointer_smoke import screen_position
else:screen_position=None


class NativePointerCoordinates(unittest.TestCase):
    def test_normal_and_high_dpi_coordinates_land_on_the_same_logical_point(self):
        self.assertIsNotNone(screen_position,'The native pointer driver has no DPI conversion')
        for rendered,ratio in [((320,120),1),((400,150),1.25),((640,240),2)]:
            with self.subTest(ratio=ratio):
                self.assertEqual(screen_position((15,30),240,rendered,ratio),(335,150))

    def test_axes_origin_and_widget_edges_use_top_left_screen_coordinates(self):
        self.assertIsNotNone(screen_position,'The native pointer driver has no DPI conversion')
        self.assertEqual(screen_position((15,30),240,(0,0),2),(15,270))
        self.assertEqual(screen_position((15,30),240,(640,480),2),(335,30))

    def test_invalid_ratio_is_rejected_before_any_os_input(self):
        self.assertIsNotNone(screen_position,'The native pointer driver has no DPI conversion')
        for ratio in (0,-1,float('nan'),float('inf')):
            with self.subTest(ratio=ratio),self.assertRaises(ValueError):screen_position((0,0),240,(10,20),ratio)
