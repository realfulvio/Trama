"""Independent point geometry and canonical round trips for perpendicular line caps."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.graph_shapes import validate_shapes
from analisi.presentation import apply_style, graph_series
from tests.test_shape_options import LINE, figure


class LineCapTests(unittest.TestCase):
    def test_caps_have_point_length_perpendicular_to_shaft_at_declared_endpoints(self):
        for dpi in (72,144):
            for heads in ('start','end','both'):
                for reverse in (False,True):
                    with self.subTest(dpi=dpi,heads=heads,reverse=reverse):
                        fig,ax=figure(dpi)
                        points=LINE['points'][::-1] if reverse else LINE['points']
                        record={**LINE,'points':points,'arrow_heads':heads,'arrow_style':'cap','arrow_size':12.}
                        before=ax.dataLim.get_points().copy(); data=ax.lines[0]
                        apply_style(fig,{'shapes':[record]}); fig.canvas.draw()
                        artist=ax._tramastat_shapes[0]
                        path=artist.get_path().transformed(artist.get_transform())
                        segments=path.to_polygons(closed_only=False)
                        self.assertEqual(len(segments),3 if heads=='both' else 2)
                        endpoints=ax.transAxes.transform(points); direction=endpoints[1]-endpoints[0]
                        caps=segments[1:]
                        expected=endpoints if heads=='both' else endpoints[[0 if heads=='start' else 1]]
                        for cap,endpoint in zip(caps,expected):
                            cap=np.asarray(cap)
                            delta=cap.max(axis=0)-cap.min(axis=0)
                            self.assertAlmostEqual(np.linalg.norm(delta)*72/dpi,12.,places=7)
                            np.testing.assert_allclose((cap.max(axis=0)+cap.min(axis=0))/2,endpoint,atol=1e-7)
                            self.assertAlmostEqual(abs((cap[0]-cap[-1])@direction),0.,places=7)
                        np.testing.assert_array_equal(ax.dataLim.get_points(),before)
                        self.assertIs(ax.lines[0],data);self.assertEqual(len(graph_series(ax)),1)

    def test_zoom_and_log_data_coordinates_keep_physical_cap_length(self):
        fig,ax=figure();ax.set(xscale='log',xlim=(1,100))
        record={**LINE,'units':'data','points':[[2.,3.],[20.,7.]],
                'arrow_heads':'both','arrow_style':'cap','arrow_size':18.}
        apply_style(fig,{'shapes':[record]})
        for limits in ((1,100),(1,1000)):
            ax.set_xlim(*limits);fig.canvas.draw()
            artist=ax._tramastat_shapes[0]
            segments=artist.get_path().transformed(artist.get_transform()).to_polygons(closed_only=False)
            for cap in segments[1:]:
                cap=np.asarray(cap)
                self.assertAlmostEqual(np.linalg.norm(cap.max(axis=0)-cap.min(axis=0))*72/fig.dpi,18.,places=7)

    def test_caps_persist_without_changing_legacy_shapes_and_export_vectors(self):
        record={**LINE,'arrow_heads':'both','arrow_style':'cap','arrow_size':14.}
        self.assertEqual(validate_shapes([record]),[record]);self.assertEqual(validate_shapes([LINE]),[LINE])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'caps.alab'
            dataset=Dataset(pd.DataFrame({'X':[1,2,3],'Y':[2,4,7]}),
                analyses=[('Linear regression',{'X':'X','Y':'Y'})],graph_styles={0:{'shapes':[record]}})
            save_project(path,{'Caps':dataset})
            loaded=load_project(path)
            self.assertEqual(loaded['Caps'].graph_styles[0]['shapes'],[record])
        fig,ax=figure();apply_style(fig,{'shapes':[record]})
        svg=BytesIO();fig.savefig(svg,format='svg');root=ET.fromstring(svg.getvalue())
        self.assertFalse(root.findall('.//{http://www.w3.org/2000/svg}image'))
        group=next(e for e in root.iter() if e.get('id')=='tramastat-shape-'+LINE['id'])
        self.assertGreaterEqual(len(group.findall('{http://www.w3.org/2000/svg}path')),3)

    def test_plain_line_can_retain_inactive_cap_preference_and_unknown_styles_fail(self):
        self.assertEqual(validate_shapes([{**LINE,'arrow_style':'cap'}])[0]['arrow_style'],'cap')
        with self.assertRaises(ValueError):validate_shapes([{**LINE,'arrow_style':'bar'}])

    def test_canvas_can_pick_the_cap_beyond_the_shaft_tolerance(self):
        from matplotlib.backend_bases import MouseEvent
        from analisi.shape_canvas import ShapeCanvas
        record={**LINE,'arrow_heads':'end','arrow_style':'cap','arrow_size':30.}
        fig,ax=figure();apply_style(fig,{'shapes':[record]});fig.canvas.draw()
        controller=ShapeCanvas(fig.canvas,ax,records=lambda:[record],commit=lambda r:None,status=lambda t:None)
        self.addCleanup(controller.close)
        points=ax.transAxes.transform(record['points']);delta=points[1]-points[0]
        perpendicular=np.array([-delta[1],delta[0]])/np.linalg.norm(delta)
        pixel=points[1]+perpendicular*10*fig.dpi/72
        event=MouseEvent('button_press_event',fig.canvas,*pixel,button=1)
        self.assertEqual(controller.hit(event),record)
