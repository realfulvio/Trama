"""Native capped-line UI, transactions, canvas operations, persistence and vector layouts."""
from copy import deepcopy
import json
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd
from matplotlib.backend_bases import MouseEvent

from . import i18n
from .data import Dataset, save_project
from .graph_shape_dialog import GraphShapesDialog, ShapeEditor, describe_shape
from .graph_shape_smoke import _pdf_objects
from .graph_shapes import SHAPES
from .presentation import apply_style


def check_line_caps(kit):
    previous=i18n.active_language()
    try:
        i18n.set_language('it'); _check(kit)
    finally:i18n.set_language(previous)


def _check(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'line-caps';out.mkdir(exist_ok=True)
    title='Native capped lines'
    frame=pd.DataFrame({'X':[1.,2,3,4,5,6],'Y':[2.1,3.9,6.2,7.8,10.1,11.9]})
    project=out/'caps.alab'
    save_project(project,{title:Dataset(frame.copy(),analyses=[('Linear regression',{'X':'X','Y':'Y'})]*2)})
    app.import_file(project);app.open_sheet(('graph',0));wait();app.dirty=False
    run=app.runs[0]

    def add(parent,heads,y,color,shot=False):
        def choose(editor):
            editor.fields['arrow_heads'].set(heads)
            editor.fields['arrow_style'].set(i18n.tr('shape.option.cap'))
            editor.fields['stroke'].set(color)
            for key,value in {'x1':'.2','x2':'.8','y1':str(y),'y2':str(y)}.items():editor.fields[key].set(value)
            editor.fields['arrow_size'].set('0');editor.ok();editor.update()
            assert editor.winfo_exists() and editor.result is None
            assert editor.focus_lastfor() is editor.widgets['arrow_size']
            editor.fields['arrow_size'].set('18,5');assert editor.preview()
            if shot:kit.capture(editor,'window-cap-editor-it.png')
            editor.ok()
        kit.drive_dialog(ShapeEditor,choose);parent.add()

    def cancel(dialog):
        add(dialog,'both',.5,'#1d6b8f');dialog.preview()
        assert SHAPES not in (run.style or {}) and not app.dirty
        dialog.cancel()
    kit.drive_dialog(GraphShapesDialog,cancel);app.edit_graph_shapes();root.update()
    assert not run.result.figure.axes[0]._tramastat_shapes and not app.dirty

    def apply(dialog):
        for heads,y,color in [('start',.25,'#1d6b8f'),('end',.5,'#b54447'),('both',.75,'#568231')]:
            add(dialog,heads,y,color,heads=='both')
        assert all(describe_shape(r)[0]==i18n.tr('shape.option.capped_line') for r in dialog.records)
        dialog.apply_button.invoke()
    kit.drive_dialog(GraphShapesDialog,apply);app.edit_graph_shapes();root.update()
    assert len(run.style[SHAPES])==3 and app.dirty

    # Reuse the direct editor: a cap remains a cap after move/undo/redo and source recalculation.
    app.start_shape_mode('select');canvas=app.graph_canvas;axes=canvas.figure.axes[0]
    def pointer(name,point):
        canvas.callbacks.process(name,MouseEvent(name,canvas,*axes.transAxes.transform(point),button=1));root.update()
    before=deepcopy(run.style)
    pointer('button_press_event',(.5,.5));pointer('motion_notify_event',(.55,.55));pointer('button_release_event',(.55,.55))
    assert run.style!=before and run.style[SHAPES][1]['arrow_style']=='cap'
    app.apply_worksheet_history();assert run.style==before
    app.apply_worksheet_history(redo=True);style=deepcopy(run.style)
    kit.capture(root,'window-line-caps.png')
    app.start_shape_mode(None);app.path=project;assert app.save()
    app.import_file(project);app.open_sheet(('graph',0));wait()
    assert app.runs[0].style==style
    app.show('data',title);app.edit_cell(0,1,'2.6');wait()
    app.current_grid.active_cell=(2,1);app.toggle_exclusion();wait()
    assert app.runs[0].style==style
    app.show('graph',0);wait()
    def export(path):
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)):app.export()
        assert path.is_file() and path.stat().st_size>1000
    for fmt in ('svg','png','pdf'):export(out/('line-caps.'+fmt))
    svg=ET.parse(out/'line-caps.svg').getroot();ns='{http://www.w3.org/2000/svg}'
    groups=[e for e in svg.iter() if 'tramastat-shape-' in (e.get('id') or '')]
    assert len(groups)==3 and [len(e.findall(ns+'path')) for e in groups]==[2,2,3]
    assert not svg.findall('.//'+ns+'image')
    _,paths,images=_pdf_objects(out/'line-caps.pdf');assert paths>=7 and images==0
    app.open_sheet(('graph',1));wait();second=app.runs[1]
    apply_style(second.result.figure,deepcopy(style));app.commit_graph_style(second,deepcopy(style))
    def compose(dialog):
        dialog.name.set('Capped-line panels');dialog.columns.set('2')
        dialog.list.selection_clear(0,'end')
        for index in range(len(dialog.runs)):dialog.list.selection_set(index)
        dialog.add_selected()
    kit.drive_dialog(kit.LayoutDialog,compose);app.new_layout();root.update()
    index=len(app.layouts)-1;app.show('layout',index);app.recalculate_layout(index);wait();app.show('layout',index)
    export(out/'layout-caps.svg');export(out/'layout-caps.pdf')
    layout=ET.parse(out/'layout-caps.svg').getroot()
    ids=[e.get('id') for e in layout.iter() if e.get('id')]
    assert len(ids)==len(set(ids)) and not layout.findall('.//'+ns+'image')
    assert len([e for e in layout.iter() if 'tramastat-shape-' in (e.get('id') or '')])==6
    _,_,images=_pdf_objects(out/'layout-caps.pdf');assert images==0
    (out/'evidence.json').write_text(json.dumps({'records':style[SHAPES],'vector_layout_panels':2,
        'svg_paths_per_line':[2,2,3],'save_reopen_recalculate':True},indent=2),encoding='utf-8')
