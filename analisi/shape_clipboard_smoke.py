"""Real system clipboard and focused canvas shortcuts, project transfer and vector export."""
from copy import deepcopy
import json
import sys
import time
import tkinter as tk
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .graph_shapes import SHAPES
from .graph_shape_smoke import _pdf_objects
from .shape_clipboard import dump_shape, load_shape
from .shape_context_smoke import LINE, BOX


def check_shape_clipboard(kit):
    language=i18n.active_language()
    try:previous=kit.get_clipboard()
    except tk.TclError:previous=''
    try:
        i18n.set_language('it')
        _check(kit)
    finally:
        i18n.set_language(language)
        if previous:kit.put_clipboard(previous)
        else:kit.root.clipboard_clear()


def _check(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'shape-clipboard';out.mkdir(exist_ok=True)
    title='Drawing clipboard data'
    frame=pd.DataFrame({'X':[1.,2.,3.,4.,5.,6.],'Y':[2.1,4.,6.1,7.9,10.,12.2]})
    line=deepcopy(LINE);box={**deepcopy(BOX),'hatch':'cross'}
    source=out/'source.alab'
    recipe=('Linear regression',{'X':'X','Y':'Y'})
    save_project(source,{title:Dataset(frame.copy(),analyses=[deepcopy(recipe),deepcopy(recipe)],
        graph_styles={0:{SHAPES:[line,box]},1:{'title':'Drawings pasted from another graph'}})})
    app.import_file(source);app.open_sheet(('graph',0));wait();root.update();app.dirty=False
    first=app.runs[0];before=deepcopy(first.style)

    def key(letter):
        widget=app.graph_canvas.get_tk_widget()
        root.lift();widget.focus_force();root.update()
        if sys.platform=='win32':
            import os
            from ctypes import byref,windll
            from ctypes.wintypes import DWORD
            pid=DWORD()
            windll.user32.GetWindowThreadProcessId(windll.user32.GetForegroundWindow(),byref(pid))
            assert pid.value==os.getpid(),'The clipboard test app is not in the foreground.'
            windll.user32.keybd_event(0x11,0,0,0)
            try:
                windll.user32.keybd_event(ord(letter.upper()),0,0,0)
                windll.user32.keybd_event(ord(letter.upper()),0,2,0)
            finally:windll.user32.keybd_event(0x11,0,2,0)
        else:widget.event_generate('<Control-'+letter+'>')
        end=time.monotonic()+.2
        while time.monotonic()<end:root.update();time.sleep(.01)

    app.start_shape_mode('select');app.shape_controller.selected=line['id'];key('c')
    text=kit.get_clipboard()  # A separate Windows Forms process reads Tk's Unicode clipboard.
    assert load_shape(text)==line and first.style==before and not app.dirty
    assert not first.shape_history.changes
    app.open_sheet(('graph',1));wait();app.start_shape_mode('select');key('v')
    destination=app.runs[1];canvas=app.graph_canvas;figure=destination.result.figure
    pasted=destination.style[SHAPES][0];line_id=pasted['id']
    assert line_id!=line['id'] and {**pasted,'id':line['id']}==line
    app.apply_worksheet_history();assert SHAPES not in destination.style
    app.apply_worksheet_history(redo=True);assert destination.style[SHAPES][0]['id']==line_id
    kit.put_clipboard(dump_shape(box))  # The independent Windows process writes the inverse direction.
    key('v');box_id=app.shape_controller.selected
    assert len(destination.style[SHAPES])==2 and box_id!=box['id']
    key('x');assert len(destination.style[SHAPES])==1
    assert load_shape(kit.get_clipboard())['id']==box_id
    app.apply_worksheet_history();assert len(destination.style[SHAPES])==2
    assert first.style==before and app.graph_canvas is canvas and destination.result.figure is figure
    pd.testing.assert_frame_equal(app.tables[title].raw,frame,check_dtype=False)

    expected=deepcopy(destination.style)
    kit.put_clipboard('1\t2\r\n3\t4\r\n')
    captured=[];original_error=app.error
    try:
        app.error=lambda error:captured.append(str(error))
        assert not app.shape_clipboard_action('paste')
    finally:app.error=original_error
    assert captured==[i18n.tr('shape.clipboard.invalid')] and destination.style==expected

    # Retain an actual translated menu and inspect the real graph after cross-graph paste.
    menu=app.make_shape_context_menu(destination,line_id)
    labels=[menu.entrycget(i,'label') for i in range(menu.index('end')+1) if menu.type(i)!='separator']
    assert all(i18n.tr('shape.clipboard.'+action) in labels for action in ('cut','copy','paste'))
    kit.capture(root,'window-drawing-clipboard.png')
    path=out/'clipboard.alab';app.path=path;assert app.save()
    app.import_file(path);app.open_sheet(('graph',1));wait()
    destination=app.runs[1];assert destination.style==expected
    app.show('data',title);app.edit_cell(0,1,'2.7');wait()
    assert destination.style==expected
    app.show('graph',1);wait()
    for extension in ('png','svg','pdf'):
        target=out/('clipboard.'+extension)
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(target)):app.export()
        assert target.stat().st_size>1000
    svg=ET.parse(out/'clipboard.svg').getroot();ns='{http://www.w3.org/2000/svg}'
    assert not svg.findall('.//'+ns+'image')
    for record in expected[SHAPES]:
        assert svg.find('.//*[@id="tramastat-shape-'+record['id']+'"]') is not None
    _,paths,images=_pdf_objects(out/'clipboard.pdf');assert paths>0 and images==0

    def compose(dialog):
        dialog.name.set('Copied drawings in two panels');dialog.columns.set('2')
        dialog.list.selection_clear(0,'end')
        for index in range(len(dialog.runs)):dialog.list.selection_set(index)
        dialog.add_selected()
    kit.drive_dialog(kit.LayoutDialog,compose);app.new_layout();root.update()
    index=len(app.layouts)-1;app.show('layout',index);app.recalculate_layout(index);wait();app.show('layout',index)
    for extension in ('svg','pdf'):
        target=out/('clipboard-layout.'+extension)
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(target)):app.export()
    layout=ET.parse(out/'clipboard-layout.svg').getroot()
    ids=[item.get('id') for item in layout.iter() if item.get('id')]
    assert len(ids)==len(set(ids)) and not layout.findall('.//'+ns+'image')
    assert len([value for value in ids if 'tramastat-shape-' in value])==4
    _,_,images=_pdf_objects(out/'clipboard-layout.pdf');assert images==0
    app.show('graph',1);wait()

    # Independent project, not a second graph in the same dataset.
    app.start_shape_mode('select');app.shape_controller.selected=line_id;key('c')
    text=kit.get_clipboard()
    other_path=out/'other-project.alab'
    save_project(other_path,{'Other project':Dataset(frame.copy(),analyses=[recipe])})
    app.import_file(other_path);app.open_sheet(('graph',0));wait();app.start_shape_mode('select')
    kit.put_clipboard(text);key('v')
    other=app.runs[0].style[SHAPES][0]
    assert other['id'] not in (line['id'],line_id)
    assert {**other,'id':line['id']}==line
    app.path=other_path;assert app.save()
    app.import_file(other_path);app.open_sheet(('graph',0));wait()
    assert app.runs[0].style[SHAPES]==[other]
    (out/'evidence.json').write_text(json.dumps({
        'system_clipboard_read_write':True,'native_canvas_shortcuts':sys.platform=='win32',
        'separate_graphs':True,'separate_projects':True,'copy_not_dirty':True,
        'cut_paste_undo_redo':True,'foreign_text_rejected':True,'data_preserved':True,
        'save_reopen_recalculate':True,'vector_svg_pdf':True,'vector_layout_panels':2,
        'copied_record':line,'pasted_ids':[line_id,box_id,other['id']]},indent=2),encoding='utf-8')
