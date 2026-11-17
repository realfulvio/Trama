"""Selection bounds and spacing use hand-computed geometry, never their implementation as an oracle."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
import uuid
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from tests.test_shape_options import BOX

_spec=importlib.util.find_spec('analisi.shape_arrange')
if _spec is not None:
    from analisi.shape_arrange import arrange_shapes
else:
    arrange_shapes=None
FIXTURE=json.loads((Path(__file__).parent/'data/shape_arrangement/fixture.json').read_text())


class ArrangementTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(arrange_shapes,'Native object arrangement is missing')
        self.fig=Figure(figsize=(6,4));FigureCanvasAgg(self.fig)
        self.ax=self.fig.add_subplot();self.ax.set(xlim=(0,100),ylim=(0,100));self.fig.canvas.draw()
        self.records=[{**deepcopy(BOX),'id':str(uuid.UUID(int=n+1)),'points':deepcopy(points),
            'hatch':'cross','hatch_color':'#e54848'} for n,points in enumerate(FIXTURE['points'].values())]
        self.ids=[r['id'] for r in self.records[:3]]

    def test_horizontal_alignments_use_only_selected_enclosing_rectangle(self):
        for mode,expected in FIXTURE['expected_x'].items():
            with self.subTest(mode=mode):
                before=deepcopy(self.records)
                result=arrange_shapes(self.ax,self.records,self.ids,horizontal=mode)
                np.testing.assert_allclose(np.array([r['points'] for r in result[:3]])[:,:,0],expected,atol=1e-12)
                for a,b in zip(result[:3],before[:3]):
                    self.assertEqual([p[1] for p in a['points']],[p[1] for p in b['points']])
                    self.assertEqual({k:v for k,v in a.items() if k!='points'}, {k:v for k,v in b.items() if k!='points'})
                self.assertEqual(result[3],before[3]);self.assertEqual(self.records,before)

    def test_vertical_alignments_and_unequal_height_gaps(self):
        for mode,expected in FIXTURE['expected_y'].items():
            with self.subTest(mode=mode):
                result=arrange_shapes(self.ax,self.records,self.ids,vertical=mode)
                np.testing.assert_allclose(np.array([r['points'] for r in result[:3]])[:,:,1],expected,atol=1e-12)
                self.assertEqual(result[3],self.records[3])

    def test_two_directions_apply_once_and_exact_noop_keeps_records(self):
        result=arrange_shapes(self.ax,self.records,self.ids,horizontal='left',vertical='top')
        np.testing.assert_allclose(np.array([r['points'] for r in result[:3]]),
            [[[.1,.7],[.2,.9]],[[.1,.7],[.3,.9]],[[.1,.8],[.2,.9]]],atol=1e-12)
        again=arrange_shapes(self.ax,result,self.ids,horizontal='left',vertical='top')
        self.assertEqual(again,result)
        self.assertEqual(arrange_shapes(self.ax,self.records,self.ids),self.records)
        self.assertIsNot(again,result)

    def test_mixed_units_and_reversed_axes_align_visually_without_rewriting_units(self):
        records=deepcopy(self.records);records[1]['units']='data';records[1]['points']=[[40,55],[60,75]]
        for reverse in (False,True):
            self.ax.set_xlim((100,0) if reverse else (0,100))
            result=arrange_shapes(self.ax,records,self.ids,horizontal='left')
            self.assertEqual(result[1]['units'],'data')
            expected=[[70,55],[90,75]] if reverse else [[10,55],[30,75]]
            np.testing.assert_allclose(result[1]['points'],expected,atol=1e-10)
            self.assertEqual(result[1]['hatch_color'],'#e54848')

    def test_logarithmic_data_translation_preserves_endpoint_display_extent(self):
        self.ax.set_xscale('log');self.ax.set_xlim(1,1000)
        records=deepcopy(self.records);records[1]['units']='data';records[1]['points']=[[10,55],[100,75]]
        before=self.ax.transData.transform(records[1]['points'])
        result=arrange_shapes(self.ax,records,self.ids,horizontal='left')
        np.testing.assert_allclose(np.array(result[1]['points'])[:,0],[10**.3,10**1.3],rtol=1e-12)
        after=self.ax.transData.transform(result[1]['points'])
        np.testing.assert_allclose(after[1]-after[0],before[1]-before[0],atol=1e-9)
        self.assertEqual(result[1]['points'][0][1],55)

    def test_invalid_selection_modes_and_insufficient_space_reject_atomically(self):
        before=deepcopy(self.records)
        for selection,options,field in [([],{},'selection'),(self.ids[:1],{},'selection'),
            ([self.ids[0],self.ids[0]],{},'selection'),([self.ids[0],str(uuid.UUID(int=99))],{},'selection'),
            (self.ids,{'horizontal':'Left'},'horizontal'),(self.ids,{'vertical':'left'},'vertical'),
            (self.ids[:2],{'horizontal':'distribute'},'selection')]:
            with self.subTest(options=options,selection=selection),self.assertRaises(ValueError) as error:
                arrange_shapes(self.ax,self.records,selection,**options)
            self.assertEqual(error.exception.field,field);self.assertEqual(self.records,before)
        crowded=deepcopy(self.records)
        for i in range(3):crowded[i]['points']=[[.1+i*.05,.2],[.6+i*.05,.4]]
        with self.assertRaises(ValueError) as error:
            arrange_shapes(self.ax,crowded,self.ids,horizontal='distribute')
        self.assertEqual(error.exception.field,'horizontal')

    def test_bad_log_domain_and_zero_extent_objects_do_not_get_partially_changed(self):
        self.ax.set_xscale('log');self.ax.set_xlim(1,1000)
        records=deepcopy(self.records);records[1].update(units='data',points=[[-1,20],[1,40]])
        with self.assertRaises(ValueError):arrange_shapes(self.ax,records,self.ids,horizontal='left')
        self.assertEqual(records[1]['points'],[[-1,20],[1,40]])
        records=deepcopy(self.records)
        for i in range(3):records[i].update(kind='line',fill=None,points=[[.1+i*.3,.2],[.1+i*.3,.4]])
        for r in records[:3]:r.pop('hatch');r.pop('hatch_color')
        result=arrange_shapes(self.ax,records,self.ids,horizontal='distribute')
        self.assertEqual(result,records)
