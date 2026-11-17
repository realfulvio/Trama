"""Real-app smoke for arrowheads and vector hatch fills; synthetic data only."""
from copy import deepcopy
import json
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd
from matplotlib.patches import FancyArrowPatch
from PIL import Image

from . import i18n
from .data import Dataset, save_project
from .graph_shape_dialog import GraphShapesDialog, ShapeEditor
from .graph_shapes import SHAPES
from .graph_shape_smoke import _fits, _pdf_objects
from .presentation import apply_style

SVG='{http://www.w3.org/2000/svg}'
TITLE='Arrow and pattern data'


def check_shape_options(kit):
    previous=i18n.active_language()
    try:
        i18n.set_language('it')
        _check(kit)
    finally:
        i18n.set_language(previous)


def _check(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'shape-options';out.mkdir(exist_ok=True)
    source=pd.DataFrame({'X':[1.,2,3,4,5,6], 'Y':[2.1,3.9,6.2,7.8,10.1,11.9]})
    data=Dataset(source.copy(),analyses=[('Linear regression',{'X':'X','Y':'Y'})]*2)
    project=out/'arrow-pattern.alab';save_project(project,{TITLE:data})
    app.import_file(project);app.open_sheet(('graph',0));wait();app.dirty=False
    initial=app.runs[0]

    def add_all(parent, *, screenshots=False):
        def arrow(editor):
            _fits(editor,(editor.preview_button,editor.ok_button,editor.cancel_button))
            editor.fields['arrow_heads'].set(i18n.tr('shape.option.both'))
            editor.fields['arrow_style'].set(i18n.tr('shape.option.filled'))
            editor.fields['arrow_size'].set('0')
            editor.widgets['arrow_size'].focus_force();editor.ok();editor.update()
            assert editor.winfo_exists() and editor.result is None
            assert editor.focus_lastfor() is editor.widgets['arrow_size']
            assert editor.problem.cget('text')
            if screenshots:kit.capture(editor,'window-arrow-size-error.png')
            editor.fields['arrow_size'].set('13,5')
            editor.fields['stroke'].set('#bf2940')
            assert editor.preview()
            if screenshots:kit.capture(editor,'window-arrow-editor-it.png')
            editor.ok();assert not editor.winfo_exists()
        kit.drive_dialog(ShapeEditor,arrow);parent.add()
        for kind,hatch,color in [('rectangle','cross','#dfedf8'),('ellipse','dots','')]:
            def box(editor,kind=kind,hatch=hatch,color=color):
                editor.fields['kind'].set(kind)
                editor.fields['hatch'].set(i18n.tr('shape.option.'+hatch))
                editor.fields['fill'].set(color)
                editor.fields['layer'].set('below')
                editor.fields['alpha'].set('0,7')
                if screenshots and kind=='rectangle':
                    editor.widgets['hatch'].focus_force();editor.scrolled.reveal(editor.widgets['hatch'])
                    kit.capture(editor,'window-hatch-editor-it.png')
                editor.ok();assert not editor.winfo_exists()
            kit.drive_dialog(ShapeEditor,box);parent.add()
        assert len(parent.records)==3
        assert parent.records[0]['arrow_heads']=='both' and parent.records[0]['arrow_style']=='filled'
        assert parent.records[0]['arrow_size']==13.5
        assert [r.get('hatch') for r in parent.records[1:]]==['cross','dots']

    def cancelled(dialog):
        add_all(dialog)
        dialog.preview();root.update()
        assert len(initial.result.figure.axes[0]._tramastat_shapes)==3
        assert SHAPES not in (initial.style or {}) and not app.dirty
        dialog.cancel()
    kit.drive_dialog(GraphShapesDialog,cancelled);app.edit_graph_shapes();root.update()
    assert not app.dirty and not initial.result.figure.axes[0]._tramastat_shapes

    def applied(dialog):
        add_all(dialog,screenshots=True);dialog.preview();dialog.apply_button.invoke()
    kit.drive_dialog(GraphShapesDialog,applied);app.edit_graph_shapes();root.update()
    style=deepcopy(app.runs[0].style);records=style[SHAPES]
    assert app.dirty and isinstance(app.runs[0].result.figure.axes[0]._tramastat_shapes[0],FancyArrowPatch)
    pd.testing.assert_frame_equal(app.tables[TITLE].raw,source,check_dtype=False)
    kit.capture(root,'window-arrows-and-hatches.png')

    # Switching through every supported direction/style uses the actual editor controls.
    for direction in ('start','end','both'):
        for head_style in ('open','filled'):
            def choose(dialog,direction=direction,head_style=head_style):
                def change(editor):
                    editor.fields['arrow_heads'].set(direction);editor.fields['arrow_style'].set(head_style)
                    editor.ok()
                dialog.tree.selection_set('0');kit.drive_dialog(ShapeEditor,change);dialog.edit()
                dialog.apply_button.invoke()
            kit.drive_dialog(GraphShapesDialog,choose);app.edit_graph_shapes();root.update()
            assert app.runs[0].style[SHAPES][0]['arrow_heads']==direction
            assert app.runs[0].style[SHAPES][0]['arrow_style']==head_style

    style=deepcopy(app.runs[0].style);records=style[SHAPES]
    app.path=project;assert app.save();app.import_file(project)
    app.open_sheet(('graph',0));wait()
    assert app.runs[0].style==style
    assert len(app.runs[0].result.figure.axes[0]._tramastat_shapes)==3
    saved=project.read_text(encoding='utf-8')
    assert 'arrow_heads' in saved and 'cross' in saved and 'A entrambe' not in saved
    app.show('data',TITLE);app.edit_cell(0,1,'2,6');wait()
    assert float(app.tables[TITLE].raw.iloc[0,1])==2.6 and app.runs[0].style==style
    app.current_grid.active_cell=(2,1);app.toggle_exclusion();wait()
    assert app.runs[0].style==style
    app.show('graph',0);wait()

    def export(path):
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)):app.export()
        assert path.exists() and path.stat().st_size>1000
    for extension in ('svg','png','pdf'):export(out/('arrows-hatches.'+extension))
    svg=ET.parse(out/'arrows-hatches.svg').getroot()
    assert len(svg.findall('.//'+SVG+'pattern'))>=2 and not svg.findall('.//'+SVG+'image')
    with Image.open(out/'arrows-hatches.png') as image:assert image.width>200 and image.height>150
    _,paths,images=_pdf_objects(out/'arrows-hatches.pdf');assert paths>=3 and images==0

    # Same shape UUIDs in two different panels must still produce unique SVG IDs.
    app.open_sheet(('graph',1));wait();run=app.runs[1]
    apply_style(run.result.figure,deepcopy(style));app.commit_graph_style(run,deepcopy(style))
    def compose(dialog):
        dialog.name.set('Arrows and patterns');dialog.columns.set('2')
        dialog.list.selection_clear(0,'end')
        for index in range(len(dialog.runs)):dialog.list.selection_set(index)
        dialog.add_selected()
    kit.drive_dialog(kit.LayoutDialog,compose);app.new_layout();root.update()
    index=len(app.layouts)-1;app.show('layout',index);app.recalculate_layout(index);wait();app.show('layout',index)
    export(out/'layout-arrows-hatches.svg');export(out/'layout-arrows-hatches.pdf')
    layout=ET.parse(out/'layout-arrows-hatches.svg').getroot()
    ids=[e.get('id') for e in layout.iter() if e.get('id')]
    assert len(ids)==len(set(ids)) and not layout.findall('.//'+SVG+'image')
    assert len(layout.findall('.//'+SVG+'pattern'))>=4
    groups=[e for e in layout.iter(SVG+'g') if 'tramastat-shape-' in (e.get('id') or '')]
    assert len(groups)==6
    _,_,images=_pdf_objects(out/'layout-arrows-hatches.pdf');assert images==0
    kit.capture(root,'window-arrow-hatch-layout.png')
    (out/'evidence.json').write_text(json.dumps({'records':records,'layout_shape_groups':len(groups),
                                               'layout_svg_ids':len(ids),'pdf_vector':True},indent=2),encoding='utf-8')
