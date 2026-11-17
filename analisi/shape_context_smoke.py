"""Actual context menus, OS right-click on Windows, canonical edits and vector round trips."""
from copy import deepcopy
import json,sys,time
from unittest.mock import patch
from tkinter import colorchooser
from xml.etree import ElementTree as ET
import pandas as pd
from matplotlib.backend_bases import MouseEvent
from . import i18n
from .data import Dataset,save_project
from .graph_shapes import SHAPES
from .graph_shape_dialog import ShapeEditor
from .graph_shape_smoke import _pdf_objects
from .presentation import apply_style

LINE={'id':'00000000-0000-4000-8000-000000002001','kind':'line','units':'axes',
      'points':[[.2,.3],[.8,.3]],'stroke':'#246d94','width':1.5,'line_style':'solid',
      'fill':None,'alpha':1.,'layer':'above','arrow_heads':'both','arrow_style':'cap','arrow_size':18.}
BOX={**LINE,'id':'00000000-0000-4000-8000-000000002002','kind':'rectangle',
     'points':[[.55,.55],[.8,.8]],'fill':'#e6f2f8'}
for key in ('arrow_heads','arrow_style','arrow_size'):BOX.pop(key)


def check_shape_context(kit):
    previous=i18n.active_language()
    try:i18n.set_language('it');_check(kit)
    finally:i18n.set_language(previous)


def _check(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'shape-context';out.mkdir(exist_ok=True)
    title='Context drawing data';frame=pd.DataFrame({'X':[1.,2,3,4,5,6],'Y':[2.1,3.9,6.2,7.8,10.1,11.9]})
    project=out/'context.alab'
    save_project(project,{title:Dataset(frame.copy(),analyses=[('Linear regression',{'X':'X','Y':'Y'})]*2,
        graph_styles={0:{SHAPES:[deepcopy(LINE),deepcopy(BOX)]}})})
    app.import_file(project);app.open_sheet(('graph',0));wait();root.update();app.dirty=False
    run=app.runs[0];canvas=app.graph_canvas;figure=run.result.figure
    def item(menu,label):
        return next(i for i in range(menu.index('end')+1) if menu.type(i)!='separator' and menu.entrycget(i,'label')==i18n.tr(label))
    def choose(sid,label,index=None):
        menu=app.make_shape_context_menu(run,sid);key=item(menu,label)
        if index is None:menu.invoke(key)
        else:menu.nametowidget(menu.entrycget(key,'menu')).invoke(index)
        root.update()
    captured=[];errors=[]
    def operate_popup():
        menu=app.shape_popup
        if menu is None:
            root.after(30,operate_popup);return
        try:
            if sys.platform!='win32':kit.capture(root,'window-shape-context.png')
            key=item(menu,'shape.context.width_line')
            menu.nametowidget(menu.entrycget(key,'menu')).invoke(5);captured.append(True)
        except Exception as error:errors.append(repr(error))
        finally:menu.unpost()
    root.after(1400 if sys.platform=='win32' else 250,operate_popup)
    if sys.platform=='win32':
        from ctypes import byref,windll
        from ctypes.wintypes import POINT,RECT,DWORD
        import os,threading
        from PIL import ImageGrab
        saved=POINT();windll.user32.GetCursorPos(byref(saved))
        widget=canvas.get_tk_widget();x,y=figure.axes[0].transAxes.transform([.5,.3])
        try:
            root.lift();widget.focus_force();root.update()
            bounds=RECT();windll.user32.GetWindowRect(int(root.wm_frame(),0),byref(bounds))
            # Keep the reference image focused on the graph and popup rather than desktop status areas.
            bbox=(bounds.left,bounds.top,bounds.right,min(bounds.bottom,bounds.top+610))
            windll.user32.SetCursorPos(round(widget.winfo_rootx()+x/canvas.device_pixel_ratio),
                round(widget.winfo_rooty()+widget.winfo_height()-y/canvas.device_pixel_ratio))
            # Native Windows menus can retain the Tk event loop. The driver uses only OS APIs in a
            # separate thread: capture the actual popup, dismiss it, then let Tk invoke its real controls.
            def dismiss_native_popup():
                time.sleep(.6)
                pid=DWORD();windll.user32.GetWindowThreadProcessId(windll.user32.GetForegroundWindow(),byref(pid))
                if pid.value!=os.getpid():
                    errors.append('The test app lost foreground focus.');return
                try:ImageGrab.grab(bbox=bbox).save(kit.directory/'window-shape-context.png')
                except Exception as error:errors.append(repr(error))
                finally:
                    windll.user32.keybd_event(0x1b,0,0,0)
                    windll.user32.keybd_event(0x1b,0,2,0)
            threading.Thread(target=dismiss_native_popup,daemon=True).start()
            windll.user32.mouse_event(8,0,0,0,0);windll.user32.mouse_event(16,0,0,0,0)
        finally:
            # Keep the cursor at the object until the actual event has been dispatched.
            deadline=time.monotonic()+8
            while not captured and not errors and time.monotonic()<deadline:root.update();time.sleep(.01)
            windll.user32.SetCursorPos(saved.x,saved.y)
    else:
        pixel=figure.axes[0].transAxes.transform([.5,.3])
        canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',canvas,*pixel,button=3))
    deadline=time.monotonic()+8
    while not captured and not errors and time.monotonic()<deadline:root.update();time.sleep(.01)
    assert captured and not errors,(captured,errors)
    assert run.style[SHAPES][0]['width']==3. and app.dirty
    assert app.graph_canvas is canvas and run.result.figure is figure
    pd.testing.assert_frame_equal(app.tables[title].raw,frame,check_dtype=False)
    before=deepcopy(run.style)
    with patch.object(colorchooser,'askcolor',return_value=(None,None)):
        choose(LINE['id'],'shape.context.color_line')
    assert run.style==before
    with patch.object(colorchooser,'askcolor',return_value=((180,60,84),'#b43c54')):
        choose(LINE['id'],'shape.context.color_line')
    choose(LINE['id'],'shape.context.style_line',1)
    choose(LINE['id'],'shape.arrow_style',0);choose(LINE['id'],'shape.arrow_style',2)
    choose(BOX['id'],'shape.hatch',2);choose(BOX['id'],'shape.context.no_fill')
    choose(BOX['id'],'shape.context.back');choose(BOX['id'],'shape.context.front')
    choose(LINE['id'],'shape.context.duplicate');duplicate=app.shape_controller.selected
    assert duplicate not in (LINE['id'],BOX['id']) and len(run.style[SHAPES])==3
    app.apply_worksheet_history();assert len(run.style[SHAPES])==2
    app.apply_worksheet_history(redo=True);assert len(run.style[SHAPES])==3
    choose(duplicate,'shape.context.remove');assert len(run.style[SHAPES])==2
    confirmed=deepcopy(run.style);position=run.shape_history.position
    def cancel(editor):
        editor.fields['width'].set('4');assert editor.preview();editor.cancel()
    kit.drive_dialog(ShapeEditor,cancel);choose(LINE['id'],'shape.context.format')
    assert run.style==confirmed and run.shape_history.position==position
    app.path=project;assert app.save();app.import_file(project);app.open_sheet(('graph',0));wait()
    run=app.runs[0];assert run.style==confirmed
    app.show('data',title);app.edit_cell(0,1,'2.6');wait()
    app.current_grid.active_cell=(2,1);app.toggle_exclusion();wait();assert run.style==confirmed
    app.show('graph',0);wait()
    def export(path):
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)):app.export()
        assert path.is_file() and path.stat().st_size>1000
    for fmt in ('png','svg','pdf'):export(out/('context.'+fmt))
    ns='{http://www.w3.org/2000/svg}';svg=ET.parse(out/'context.svg').getroot()
    assert not svg.findall('.//'+ns+'image')
    _,_,images=_pdf_objects(out/'context.pdf');assert images==0
    (out/'evidence.json').write_text(json.dumps({'native_right_click':sys.platform=='win32',
        'menu_popup':True,'canonical_records':confirmed[SHAPES],'save_reopen_recalculate':True,
        'undo_redo':True,'cancel_unchanged':True},indent=2),encoding='utf-8')
