"""Real arrangement selection, field correction, cancellation and vector project round trips."""
from copy import deepcopy
import json
from unittest.mock import patch
from xml.etree import ElementTree as ET
import numpy as np
import pandas as pd
from .data import Dataset,save_project
from .graph_shapes import SHAPES
from .shape_arrange_dialog import ArrangeShapesDialog
from .graph_shape_smoke import _pdf_objects
from . import i18n


def check_shape_arrange(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'shape-arrange';out.mkdir(exist_ok=True)
    frame=pd.DataFrame({'X':[1.,2.,3.,4.,5.,6.],'Y':[2.1,3.9,6.2,7.8,10.1,11.9]})
    points=[[[.1,.2],[.2,.4]],[[.4,.55],[.6,.75]],[[.75,.8],[.85,.9]],[[.01,.01],[.05,.06]]]
    records=[{'id':f'00000000-0000-4000-8000-{i+7000:012d}','kind':'rectangle','units':'axes',
        'points':pair,'stroke':'#184e77','width':1.5,'line_style':'solid','fill':'#fff1b8',
        'alpha':1.,'layer':'above','hatch':'cross','hatch_color':'#9e4f93'} for i,pair in enumerate(points)]
    ids=[r['id'] for r in records[:3]];title='Arrange drawing objects'
    project=out/'arrange.alab';recipe=('Linear regression',{'X':'X','Y':'Y'})
    save_project(project,{title:Dataset(frame.copy(),analyses=[deepcopy(recipe),deepcopy(recipe)],
        graph_styles={0:{SHAPES:records}})})
    app.import_file(project);app.open_sheet(('graph',0));wait();root.update()
    run=app.runs[0];before=deepcopy(run.style);source_before=app.tables[title].raw.copy(deep=True);app.dirty=False
    def cancel(dialog):
        dialog.tree.selection_remove(*dialog.tree.selection());dialog.apply_button.focus_force();dialog.update()
        dialog.ok();dialog.update();assert dialog.winfo_exists() and dialog.focus_get() is dialog.tree
        dialog.tree.selection_set(ids);dialog.fields['horizontal'].set('left');dialog.fields['vertical'].set('top')
        assert dialog.preview() and run.style==before and not app.dirty
        kit.capture(dialog,'window-shape-arrange-dialog.png');dialog.cancel()
    kit.drive_dialog(ArrangeShapesDialog,cancel);app.arrange_graph_shapes()
    assert run.style==before and not app.dirty
    def accept(dialog):
        dialog.tree.selection_set(ids);dialog.fields['horizontal'].set('distribute');dialog.fields['vertical'].set('middle')
    kit.drive_dialog(ArrangeShapesDialog,accept)
    # Invoke the actual Arrange menu command, retaining startup-language labels even after other smokes.
    menu=app.menu
    titles={i18n._EN['menu.arrange'],i18n._IT['menu.arrange']}
    commands={i18n._EN['command.arrange_shapes'],i18n._IT['command.arrange_shapes']}
    top=next(i for i in range(menu.index('end')+1) if menu.type(i)=='cascade' and menu.entrycget(i,'label') in titles)
    popup=menu.nametowidget(menu.entrycget(top,'menu'))
    item=next(i for i in range(popup.index('end')+1) if popup.type(i)!='separator' and popup.entrycget(i,'label') in commands)
    popup.invoke(item);root.update()
    expected=deepcopy(run.style)
    np.testing.assert_allclose(np.array([r['points'] for r in expected[SHAPES][:3]]),
        [[[.1,.45],[.2,.65]],[[.375,.45],[.575,.65]],[[.75,.5],[.85,.6]]],atol=1e-12)
    assert expected[SHAPES][3]==records[3]
    app.apply_worksheet_history();assert run.style==before
    app.apply_worksheet_history(redo=True);assert run.style==expected
    pd.testing.assert_frame_equal(app.tables[title].raw,source_before)
    kit.capture(root,'window-shapes-arranged.png')
    app.path=project;assert app.save();app.import_file(project);app.open_sheet(('graph',0));wait()
    run=app.runs[0];assert run.style==expected
    app.show('data',title);app.edit_cell(0,1,'2.8');wait();assert run.style==expected
    app.show('graph',0);wait()
    def export(path):
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)):app.export()
        assert path.stat().st_size>1000
    for extension in ('png','svg','pdf'):export(out/('arranged.'+extension))
    ns='{http://www.w3.org/2000/svg}'
    assert not ET.parse(out/'arranged.svg').getroot().findall('.//'+ns+'image')
    _,paths,images=_pdf_objects(out/'arranged.pdf');assert paths>0 and images==0
    def compose(dialog):
        dialog.name.set('Arranged drawings');dialog.columns.set('2');dialog.list.selection_set(0,'end');dialog.add_selected()
    kit.drive_dialog(kit.LayoutDialog,compose);app.new_layout();root.update()
    index=len(app.layouts)-1;app.show('layout',index);app.recalculate_layout(index);wait();app.show('layout',index)
    for extension in ('svg','pdf'):export(out/('arranged-layout.'+extension))
    assert not ET.parse(out/'arranged-layout.svg').getroot().findall('.//'+ns+'image')
    _,_,images=_pdf_objects(out/'arranged-layout.pdf');assert images==0
    (out/'evidence.json').write_text(json.dumps({'actual_arrange_menu':True,'selection_error_focus':True,
        'preview_cancel':True,'single_transaction_undo_redo':True,'unchanged_unselected':True,
        'save_reopen_recalculate':True,'vector_graph_and_layout':True,'records':expected[SHAPES]},indent=2))
