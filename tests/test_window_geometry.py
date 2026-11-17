"""The decorated window must fit the usable monitor, including on secondary screens."""
import unittest

from analisi.window_geometry import clamp_rect


class WindowGeometryTests(unittest.TestCase):
    def test_titlebar_and_taskbar_count_towards_available_height(self):
        self.assertEqual(clamp_rect((141, 172, 914, 780), (0, 0, 1024, 720)), (141, 112))

    def test_already_visible_rectangle_does_not_move(self):
        self.assertEqual(clamp_rect((141, 100, 914, 708), (0, 0, 1024, 720)), (141, 100))

    def test_secondary_monitor_can_have_negative_coordinates(self):
        self.assertEqual(clamp_rect((-1928, 100, -1155, 708), (-1920, 0, 0, 1040)), (-1920, 100))

    def test_oversize_rectangle_aligns_with_work_area_origin(self):
        self.assertEqual(clamp_rect((100, 100, 2100, 1200), (0, 0, 1024, 720)), (0, 0))
