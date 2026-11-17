"""A separate native hatch color preserves legacy shapes, rendering and vector content."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba

from analisi.data import Dataset,load_project,save_project
from analisi.graph_shapes import validate_shapes
from analisi.presentation import apply_style
from analisi.shape_clipboard import dump_shape,load_shape
from analisi.shape_context import edit_records
from tests.test_shape_options import BOX,LINE,figure


class PatternColorTests(unittest.TestCase):
    def test_area_color_is_optional_canonical_and_independent(self):
        self.assertEqual(validate_shapes([BOX]),[BOX])
        record={**BOX,'hatch':'cross','hatch_color':'#e54848','stroke':'#184e77','fill':'#fff1b8'}
        self.assertEqual(validate_shapes([record]),[record])
        fig,ax=figure();apply_style(fig,{'shapes':[record]})
        self.assertEqual(len(ax._tramastat_shapes),1)
        artist=ax._tramastat_shapes[0]
        self.assertEqual(artist.get_hatchcolor(),to_rgba(record['hatch_color'],record['alpha']))
        self.assertEqual(artist.get_edgecolor(),to_rgba(record['stroke'],record['alpha']))
        self.assertEqual(artist.get_facecolor(),to_rgba(record['fill'],record['alpha']))

    def test_invalid_pattern_colors_and_line_scope_are_rejected(self):
        for value in (None,True,0,'','none','edge','invalid',[],{'color':'red'}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_shapes([{**BOX,'hatch_color':value}])
        with self.assertRaises(ValueError):validate_shapes([{**LINE,'hatch_color':'red'}])

    def test_color_survives_project_and_clipboard_and_can_follow_border_again(self):
        record={**BOX,'hatch':'dots','hatch_color':'#de542e'}
        self.assertEqual(load_shape(dump_shape(record)),record)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'patterns.alab'
            save_project(p,{'A':Dataset(pd.DataFrame({'X':[1,2],'Y':[3,4]}),
                analyses=[('Linear regression',{'X':'X','Y':'Y'})],graph_styles={0:{'shapes':[record]}})})
            loaded=load_project(p)['A'].graph_styles[0]['shapes'][0]
            self.assertEqual(loaded,record)
        restored,_=edit_records([record],record['id'],'hatch_color',None)
        expected=deepcopy(record);expected.pop('hatch_color')
        self.assertEqual(restored,[expected])
        again,_=edit_records(restored,record['id'],'hatch_color',None)
        self.assertEqual(again,restored)

    def test_transparent_area_and_ellipse_keep_alpha_and_one_artist_each(self):
        for kind in ('rectangle','ellipse'):
            record={**BOX,'kind':kind,'fill':None,'hatch':'diagonal','hatch_color':'#a62467','alpha':.4}
            fig,ax=figure();apply_style(fig,{'shapes':[record]});fig.canvas.draw()
            self.assertEqual(len(ax._tramastat_shapes),1)
            artist=ax._tramastat_shapes[0]
            self.assertEqual(artist.get_hatchcolor(),to_rgba('#a62467',.4))
            self.assertEqual(artist.get_facecolor()[-1],0)

    def test_legacy_border_following_and_pixels_do_not_change_when_property_absent(self):
        record={**BOX,'hatch':'cross','stroke':'#307850'}
        fig,ax=figure();apply_style(fig,{'shapes':[record]});fig.canvas.draw()
        before=np.asarray(fig.canvas.buffer_rgba()).copy()
        self.assertEqual(ax._tramastat_shapes[0].get_hatchcolor(),to_rgba(record['stroke'],record['alpha']))
        apply_style(fig,{'shapes':[deepcopy(record)]});fig.canvas.draw()
        np.testing.assert_array_equal(before,np.asarray(fig.canvas.buffer_rgba()))
        self.assertEqual(validate_shapes([record]),[record])

    def test_svg_pattern_border_and_face_have_distinct_colors(self):
        record={**BOX,'hatch':'cross','hatch_color':'#e54848','stroke':'#184e77','fill':'#fff1b8'}
        fig,ax=figure();apply_style(fig,{'shapes':[record]})
        buf=BytesIO();fig.savefig(buf,format='svg');root=ET.fromstring(buf.getvalue())
        ns='{http://www.w3.org/2000/svg}'
        self.assertFalse(root.findall('.//'+ns+'image'))
        pattern=root.find('.//'+ns+'pattern');self.assertIsNotNone(pattern)
        self.assertTrue(any('#e54848' in x.get('style','') for x in pattern.iter()))
        group=root.find('.//*[@id="tramastat-shape-'+record['id']+'"]')
        self.assertTrue(any('#184e77' in x.get('style','') for x in group.iter()))
        self.assertTrue(any('#fff1b8' in ' '.join(x.attrib.values()) for x in pattern.iter()))

    def test_pdf_pattern_renders_in_its_own_color_and_remains_vector(self):
        import pypdfium2 as pdfium
        from analisi.graph_shape_smoke import _pdf_objects
        record={**BOX,'hatch':'cross','hatch_color':'#e54848','stroke':'#184e77','fill':'#fff1b8'}
        fig,ax=figure();apply_style(fig,{'shapes':[record]})
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'pattern.pdf';fig.savefig(p)
            _,paths,images=_pdf_objects(p)
            self.assertGreater(paths,0);self.assertEqual(images,0)
            document=pdfium.PdfDocument(str(p))
            try:
                page=document[0]
                try:
                    bitmap=page.render(scale=2)
                    try:pixels=np.asarray(bitmap.to_pil().convert('RGB'))
                    finally:bitmap.close()
                finally:page.close()
            finally:document.close()
            red=(pixels[:,:,0]>160)&(pixels[:,:,1]<120)&(pixels[:,:,2]<130)
            self.assertGreater(int(red.sum()),100)
