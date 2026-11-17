"""Decorations must stay separate from data when users autoscale again."""
from unittest import TestCase

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from analisi.axis_guides import AXIS_BANDS, AXIS_GUIDES
from analisi.presentation import apply_style


class GuideAutoscaleTests(TestCase):
    def test_opposite_ticks_outside_the_view_do_not_expand_export_bounds(self):
        figure = Figure(figsize=(5, 3))
        FigureCanvasAgg(figure)
        axes = figure.subplots()
        axes.plot([1., 2., 3.], [2., 3., 4.])
        apply_style(figure, {})
        figure.canvas.draw()
        expected = figure.get_tightbbox(figure.canvas.get_renderer()).bounds
        apply_style(figure, {AXIS_GUIDES: [{
            'id': 'e0000000-0000-4000-8000-000000000001', 'axis': 'x', 'value': 100.,
            'line': False, 'tick': True, 'side': 'opposite', 'label': 'outside'}]})
        figure.canvas.draw()
        np.testing.assert_allclose(figure.get_tightbbox(figure.canvas.get_renderer()).bounds, expected)
        marker = next(a for a in axes.get_children() if str(a.get_gid()).endswith(':tick'))
        self.assertIsNone(marker.get_tightbbox(figure.canvas.get_renderer()))
        axes.set_xlim(90., 110.)
        figure.canvas.draw()
        self.assertIsNotNone(marker.get_tightbbox(figure.canvas.get_renderer()))

    def test_relim_and_autoscale_exclude_lines_opposite_ticks_and_bands(self):
        uid = 'e0000000-0000-4000-8000-000000000001'
        cases = [
            {AXIS_GUIDES: [{'id': uid, 'axis': 'x', 'value': 100., 'line': True}]},
            {AXIS_GUIDES: [{'id': uid, 'axis': 'x', 'value': 100., 'line': False,
                           'tick': True, 'side': 'opposite', 'label': 'outside'}]},
            {AXIS_BANDS: [{'id': uid, 'axis': 'y', 'lower': 50., 'upper': 60., 'color': '#4488aa'}]},
        ]
        for style in cases:
            with self.subTest(style=style):
                figure = Figure()
                FigureCanvasAgg(figure)
                axes = figure.subplots()
                axes.plot([1., 2., 3.], [2., 3., 4.])
                expected = axes.dataLim.get_points().copy()
                limits = axes.get_xlim(), axes.get_ylim()
                apply_style(figure, style)
                axes.relim()
                np.testing.assert_array_equal(axes.dataLim.get_points(), expected)
                axes.autoscale(enable=True)
                np.testing.assert_allclose(axes.get_xlim(), limits[0])
                np.testing.assert_allclose(axes.get_ylim(), limits[1])
                figure.canvas.draw()
