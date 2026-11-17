"""Native arrowheads and hatch fills: independent geometry and persistence checks."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch

from analisi.data import Dataset, load_project, save_project
from analisi.graph_shapes import validate_shapes
from analisi.presentation import apply_style, graph_series
from analisi.workbench import analyse

LINE = {'id':'00000000-0000-4000-8000-000000000101','kind':'line','units':'axes',
        'points':[[.15,.25],[.8,.7]],'stroke':'#194e78','width':1.5,'line_style':'solid',
        'fill':None,'alpha':1.,'layer':'above'}
BOX = {**LINE, 'id':'00000000-0000-4000-8000-000000000102','kind':'rectangle','fill':'#e6f2f8'}
SVG='{http://www.w3.org/2000/svg}'


def figure(dpi=100):
    fig=Figure(figsize=(4,3),dpi=dpi); FigureCanvasAgg(fig)
    ax=fig.add_axes([.2,.2,.6,.6]);ax.plot([1,2,4,6],[2,4,7,8],label='Data')
    ax.set(xlim=(0,10),ylim=(0,10));return fig,ax


class ShapeOptionsTests(unittest.TestCase):
    def test_legacy_records_and_artists_are_unchanged(self):
        self.assertEqual(validate_shapes([LINE, BOX]),[LINE,BOX])
        fig,ax=figure();apply_style(fig,{'shapes':[deepcopy(LINE)]})
        self.assertIsInstance(ax._tramastat_shapes[0],Line2D)
        self.assertEqual(len(ax.lines),2)

    def test_optional_keys_round_trip_only_when_supplied(self):
        arrow={**LINE,'arrow_heads':'both','arrow_style':'filled','arrow_size':14.}
        box={**BOX,'hatch':'cross'}
        self.assertEqual(validate_shapes([arrow,box]),[arrow,box])
        normalized=validate_shapes([arrow,box]);normalized[0]['points'][0][0]=0
        self.assertEqual(arrow['points'][0][0],.15)

    def test_strict_optional_scope_and_values(self):
        for key,bad in [('arrow_heads','back'),('arrow_style','triangle'),('arrow_size',True),
                        ('arrow_size',float('nan')),('arrow_size',float('inf')),('arrow_size',0),
                        ('arrow_size',41),('hatch','unknown')]:
            base=BOX if key=='hatch' else LINE
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):validate_shapes([{**base,key:bad}])
        for invalid in ({**LINE,'hatch':'cross'},{**BOX,'arrow_heads':'end'},{**LINE,'unexpected':1}):
            with self.assertRaises(ValueError):validate_shapes([invalid])

    def test_all_arrows_keep_data_limits_artist_identity_and_layer(self):
        for heads in ('start','end','both'):
            for style in ('open','filled'):
                with self.subTest(heads=heads,style=style):
                    fig,ax=figure();data=ax.lines[0]
                    before=ax.dataLim.get_points().copy(),ax.get_xlim(),ax.get_ylim()
                    record={**LINE,'arrow_heads':heads,'arrow_style':style,'arrow_size':12.}
                    apply_style(fig,{'shapes':[record]});fig.canvas.draw()
                    artist=ax._tramastat_shapes[0]
                    self.assertIsInstance(artist,FancyArrowPatch)
                    self.assertIs(ax.lines[0],data);self.assertEqual(len(ax.lines),1)
                    self.assertEqual(artist.get_gid(),'tramastat-shape-'+LINE['id'])
                    np.testing.assert_array_equal(ax.dataLim.get_points(),before[0])
                    self.assertEqual((ax.get_xlim(),ax.get_ylim()),before[1:])
                    self.assertEqual(len(graph_series(ax)),1)
                    apply_style(fig,{'shapes':[record]});fig.canvas.draw()
                    self.assertEqual(len(ax.patches),1)
                    self.assertEqual(artist.axes,None)

    def test_arrow_geometry_uses_requested_coordinate_transform(self):
        for units,points in [('axes',[[.15,.25],[.8,.7]]),('data',[[1.5,2.5],[8,7]])]:
            fig,ax=figure();record={**LINE,'units':units,'points':points,'arrow_heads':'end'}
            apply_style(fig,{'shapes':[record]});fig.canvas.draw();artist=ax._tramastat_shapes[0]
            display=artist.get_transform().transform(artist.get_path().vertices)
            expected=(ax.transAxes if units=='axes' else ax.transData).transform(points)
            self.assertLess(np.linalg.norm(display[0]-expected[0]),2.)
            self.assertLess(np.min(np.linalg.norm(display-expected[1],axis=1)),3.)

    def test_hatches_are_svg_patterns_with_no_raster_images(self):
        for kind in ('rectangle','ellipse'):
            for hatch in ('diagonal','cross','dots'):
                with self.subTest(kind=kind,hatch=hatch):
                    fig,ax=figure();record={**BOX,'kind':kind,'hatch':hatch}
                    apply_style(fig,{'shapes':[record]});fig.canvas.draw()
                    self.assertTrue(ax._tramastat_shapes[0].get_hatch())
                    buf=BytesIO();fig.savefig(buf,format='svg');root=ET.fromstring(buf.getvalue())
                    self.assertTrue(root.findall('.//'+SVG+'pattern'))
                    self.assertFalse(root.findall('.//'+SVG+'image'))
                    self.assertEqual(len(graph_series(ax)),1)

    def test_persistence_recalculation_and_svg_uses_the_same_records(self):
        frame=pd.DataFrame({'X':[1.,2,3,4,5],'Y':[2.1,4.,6.2,7.8,10.1]})
        options={'X':'X','Y':'Y'};dataset=Dataset(frame,analyses=[('Linear regression',options)])
        shapes=[{**LINE,'arrow_heads':'both','arrow_style':'filled','arrow_size':18.},{**BOX,'hatch':'dots'}]
        dataset.graph_styles[0]={'shapes':deepcopy(shapes)}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shapes.alab';save_project(path,{'Data':dataset})
            loaded=load_project(path)['Data'];self.assertEqual(loaded.graph_styles[0],{'shapes':shapes})
            loaded.raw.loc[0,'Y']=2.3
            result=analyse('Linear regression',loaded.raw,options)
            apply_style(result.figure,loaded.graph_styles[0]);result.figure.canvas.draw()
            self.assertEqual(len(result.figure.axes[0]._tramastat_shapes),2)
            self.assertEqual(loaded.graph_styles[0],{'shapes':shapes})

    def test_arrowhead_area_in_points_survives_zoom_and_dpi(self):
        from matplotlib.path import Path as MplPath
        areas=[]
        for dpi,limits in ((100,(0,10)),(100,(0,30)),(200,(0,30))):
            fig,ax=figure(dpi);ax.set_xlim(*limits)
            record={**LINE,'units':'data','points':[[1.5,2.5],[8.,7.]],
                    'arrow_heads':'end','arrow_style':'filled','arrow_size':16.}
            apply_style(fig,{'shapes':[record]});fig.canvas.draw()
            artist=ax._tramastat_shapes[0];path=artist.get_path()
            vertices=artist.get_transform().transform(path.vertices)/(dpi/72)
            closed=[];current=[]
            for vertex,code in zip(vertices,path.codes):
                if code==MplPath.MOVETO:current=[vertex]
                elif code==MplPath.LINETO:current.append(vertex)
                elif code==MplPath.CLOSEPOLY:
                    points=np.asarray(current)
                    if len(points)>=3:
                        area=.5*abs(points[:,0]@np.roll(points[:,1],-1)-points[:,1]@np.roll(points[:,0],-1))
                        if area>0:closed.append(area)
            self.assertEqual(len(closed),1)
            areas.append(closed[0])
        self.assertGreater(areas[0],1.)
        np.testing.assert_allclose(areas,areas[0],rtol=1e-9,atol=1e-9)

    def test_transparent_hatches_and_arrow_layouts_remain_vector_and_resolve_ids(self):
        import re
        from analisi.layout_svg import export_layout_svg
        from analisi.figure_export import export_figure
        import pypdfium2 as pdfium
        from pypdfium2 import raw as pdfraw
        fig,ax=figure()
        apply_style(fig,{'shapes':[{**BOX,'fill':None,'hatch':'cross'},
                                 {**LINE,'arrow_heads':'both','arrow_style':'filled','arrow_size':18.}]})
        with tempfile.TemporaryDirectory() as directory:
            svg=Path(directory)/'layout.svg';pdf=Path(directory)/'graph.pdf'
            export_layout_svg('Arrow and hatch',2,[fig,fig],svg,{'svg_text':'text'})
            tree=ET.parse(svg).getroot();ids=[e.attrib['id'] for e in tree.iter() if 'id' in e.attrib]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertGreaterEqual(len(tree.findall('.//'+SVG+'pattern')),2)
            self.assertFalse(tree.findall('.//'+SVG+'image'))
            for element in tree.iter():
                for value in element.attrib.values():
                    for target in re.findall(r'url\(#([^)]*)\)',value):self.assertIn(target,ids)
            export_figure(fig,pdf,{'format':'pdf','width_mm':101.6})
            doc=pdfium.PdfDocument(str(pdf))
            try:
                page=doc[0]
                try:
                    types=[o.type for o in page.get_objects(max_depth=15)]
                    self.assertIn(pdfraw.FPDF_PAGEOBJ_PATH,types)
                    self.assertNotIn(pdfraw.FPDF_PAGEOBJ_IMAGE,types)
                finally:page.close()
            finally:doc.close()
