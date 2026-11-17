"""Real pattern-color editor/menu, cancellation, clipboard and vector round trips."""
from copy import deepcopy
import json
from unittest.mock import patch
from xml.etree import ElementTree as ET
import pandas as pd

from . import i18n
from .data import Dataset,save_project
from .graph_shape_dialog import ShapeEditor
from .graph_shapes import SHAPES
from .graph_shape_smoke import _pdf_objects

BOX={'id':'00000000-0000-4000-8000-000000006901','kind':'rectangle','units':'axes',
     'points':[[.18,.48],[.47,.82]],'stroke':'#184e77','width':2.,'line_style':'solid',
     'fill':'#fff1b8','alpha':1.,'layer':'above','hatch':'cross','hatch_color':'#e54848'}
ELLIPSE={**BOX,'id':'00000000-0000-4000-8000-000000006902','kind':'ellipse',
         'points':[[.6,.2],[.88,.52]],'fill':None,'hatch':'diagonal','hatch_color':'#238b63'}


def check_shape_pattern_color(kit):
    previous=i18n.active_language()
    try:i18n.set_language('it');_check(kit)
    finally:i18n.set_language(previous)


def _check(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'pattern-color';out.mkdir(exist_ok=True)
    frame=pd.DataFrame({'X':[1.,2.,3.,4.,5.,6.],'Y':[2.1,3.9,6.2,7.8,10.1,11.9]})
    title='Independent pattern colors';project=out/'patterns.alab'
    recipe=('Linear regression',{'X':'X','Y':'Y'})
    save_project(project,{title:Dataset(frame.copy(),analyses=[deepcopy(recipe),deepcopy(recipe)],
        graph_styles={0:{SHAPES:[deepcopy(BOX),deepcopy(ELLIPSE)]}})})
    app.import_file(project);app.open_sheet(('graph',0));wait();root.update()
    run=app.runs[0];before=deepcopy(run.style);app.dirty=False
    def cancel(editor):
        editor.fields['hatch_color'].set('not-a-color')
        editor.notebook.select(editor.pages['position'])
        editor.ok_button.focus_force();editor.update();editor.ok();editor.update()
        assert editor.winfo_exists() and editor.focus_get() is editor.widgets['hatch_color'], 'Invalid pattern color must receive keyboard focus'
        assert editor.notebook.select()==str(editor.pages['appearance'])
        editor.fields['hatch_color'].set('#9e4f93');assert editor.preview()
        assert run.style==before
        kit.capture(editor,'window-pattern-color-editor.png');editor.cancel()
    kit.drive_dialog(ShapeEditor,cancel);app.edit_canvas_shape(BOX['id'])
    assert run.style==before and not app.dirty
    def accept(editor):
        editor.fields['hatch_color'].set('#9e4f93');editor.ok()
    kit.drive_dialog(ShapeEditor,accept);app.edit_canvas_shape(BOX['id'])
    assert run.style[SHAPES][0]=={**BOX,'hatch_color':'#9e4f93'}
    app.apply_worksheet_history();assert run.style==before
    app.apply_worksheet_history(redo=True)
    menu=app.make_shape_context_menu(run,BOX['id'])
    index=next(i for i in range(menu.index('end')+1) if menu.type(i)!='separator'
               and menu.entrycget(i,'label')==i18n.tr('shape.context.pattern_follow'))
    menu.invoke(index);assert 'hatch_color' not in run.style[SHAPES][0]
    app.apply_worksheet_history();assert run.style[SHAPES][0]['hatch_color']=='#9e4f93'
    expected=deepcopy(run.style);kit.capture(root,'window-pattern-colors.png')
    app.shape_clipboard_action('copy',run=run,shape_id=BOX['id'])
    app.open_sheet(('graph',1));wait();assert app.shape_clipboard_action('paste')
    pasted=app.runs[1].style[SHAPES][0]
    assert pasted['id']!=BOX['id'] and pasted['hatch_color']=='#9e4f93'
    app.path=project;assert app.save();app.import_file(project);app.open_sheet(('graph',0));wait()
    run=app.runs[0];assert run.style==expected
    app.show('data',title);app.edit_cell(0,1,'2.8');wait();assert run.style==expected
    app.show('graph',0);wait()
    def export(path):
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)):app.export()
        assert path.stat().st_size>1000
    for extension in ('png','svg','pdf'):export(out/('patterns.'+extension))
    ns='{http://www.w3.org/2000/svg}'
    svg=ET.parse(out/'patterns.svg').getroot();assert not svg.findall('.//'+ns+'image')
    colors=' '.join(' '.join(node.attrib.values()) for node in svg.findall('.//'+ns+'pattern'))
    # Pattern child paths carry their own color rather than the border's color.
    colors=' '.join(' '.join(node.attrib.values()) for pat in svg.findall('.//'+ns+'pattern') for node in pat.iter())
    assert '#9e4f93' in colors and '#238b63' in colors
    _,paths,images=_pdf_objects(out/'patterns.pdf');assert paths>0 and images==0
    def compose(dialog):
        dialog.name.set('Independent pattern colors');dialog.columns.set('2')
        dialog.list.selection_set(0,'end');dialog.add_selected()
    kit.drive_dialog(kit.LayoutDialog,compose);app.new_layout();root.update()
    index=len(app.layouts)-1;app.show('layout',index);app.recalculate_layout(index);wait();app.show('layout',index)
    export(out/'patterns-layout.svg');export(out/'patterns-layout.pdf')
    layout=ET.parse(out/'patterns-layout.svg').getroot();ids=[node.get('id') for node in layout.iter() if node.get('id')]
    assert len(ids)==len(set(ids)) and not layout.findall('.//'+ns+'image')
    _,_,images=_pdf_objects(out/'patterns-layout.pdf');assert images==0
    (out/'evidence.json').write_text(json.dumps({'preview_cancel':True,'error_page_focus':True,
        'undo_redo':True,'independent_colors':True,'clipboard':True,'save_reopen_recalculate':True,
        'vector_graph_and_layout':True,'records':expected[SHAPES]},indent=2),encoding='utf-8')
