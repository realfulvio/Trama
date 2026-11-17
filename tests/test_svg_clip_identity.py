"""Opaque backend identifiers are not drawing differences; clip geometry still is."""
import unittest
from analisi.shape_canvas_smoke import _canonical_clip_ids


def svg(clip='p0123456789',width='10',shape='tramastat-shape-a'):
    return (f'<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="{clip}">'
            f'<rect x="0" y="0" width="{width}" height="4"/></clipPath></defs>'
            f'<g id="{shape}" clip-path="url(#{clip})"><path d="M0 0 L10 4"/></g></svg>').encode()


class SVGClipIdentityTests(unittest.TestCase):
    def test_opaque_clip_name_and_matching_reference_do_not_change_geometry(self):
        self.assertEqual(_canonical_clip_ids(svg()),_canonical_clip_ids(svg(clip='pabcdefabcd')))

    def test_clip_geometry_is_never_normalized_away(self):
        self.assertNotEqual(_canonical_clip_ids(svg()),_canonical_clip_ids(svg(width='10.01')))

    def test_stable_drawing_identity_is_never_normalized_away(self):
        self.assertNotEqual(_canonical_clip_ids(svg()),_canonical_clip_ids(svg(shape='tramastat-shape-b')))
