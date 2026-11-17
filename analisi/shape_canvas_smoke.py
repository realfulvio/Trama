"""Real app canvas transactions, Windows OS pointer input and export/persistence acceptance."""
from copy import deepcopy
from io import BytesIO
import json
import sys
import time
from unittest.mock import patch
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib import rc_context
from matplotlib.backend_bases import MouseEvent

from .data import Dataset, save_project
from .graph_shape_dialog import ShapeEditor
from .graph_shapes import SHAPES
from .i18n import tr


def _canonical_clip_ids(data):
    """Ignore opaque SVG clip IDs while comparing every clip geometry and reference."""
    root = ET.fromstring(data)
    ids = {node.get('id'): f'clip-{index}' for index,node in
           enumerate(root.iter('{http://www.w3.org/2000/svg}clipPath'))}
    for node in root.iter():
        for key,value in list(node.attrib.items()):
            if key == 'id' and value in ids:
                node.set(key,ids[value])
            else:
                for old,new in ids.items():
                    value = value.replace('url(#'+old+')','url(#'+new+')')
                    if key.endswith('href') and value == '#'+old:value = '#'+new
                node.set(key,value)
    return ET.tostring(root)


def check_shape_canvas(kit):
    app, root, wait = kit.app, kit.root, kit.wait_for_calculation
    out = kit.directory / 'canvas-shapes'; out.mkdir(exist_ok=True)
    frame = pd.DataFrame({'X':[1.,2,3,4,5,6], 'Y':[2.1,3.9,6.2,7.8,10.1,11.9]})
    title = 'Canvas drawing data'
    project = out / 'canvas.alab'
    save_project(project, {title:Dataset(frame.copy(), analyses=[('Linear regression',{'X':'X','Y':'Y'})]*2)})
    app.import_file(project); app.open_sheet(('graph',0)); wait(); root.update()
    run = app.runs[0]; app.dirty = False
    fig = run.result.figure; ax = fig.axes[0]
    original_limits = (ax.get_xlim(), ax.get_ylim(), ax.dataLim.get_points().copy())

    def choose_mode(mode):
        stack=[app.page]
        while stack:
            widget=stack.pop()
            if widget.winfo_class()=='TMenubutton' and widget.cget('menu'):
                menu=widget.nametowidget(widget.cget('menu'))
                if menu.entrycget(0,'label')==tr('shape.canvas.manage'):
                    label=tr('shape.canvas.stop' if mode is None else 'shape.canvas.'+mode)
                    index=next(i for i in range(menu.index('end')+1)
                               if menu.type(i)!='separator' and menu.entrycget(i,'label')==label)
                    menu.invoke(index)
                    assert app.shape_controller.mode==mode
                    return
            stack.extend(widget.winfo_children())
        raise AssertionError('Native drawing menu missing')

    def event(name, point, **kwargs):
        canvas = app.graph_canvas
        pixels = canvas.figure.axes[0].transAxes.transform(point)
        canvas.callbacks.process(name, MouseEvent(name, canvas, *pixels, button=1, **kwargs))
        root.update()

    def drag(start, end, **kwargs):
        event('button_press_event',start,**kwargs)
        event('motion_notify_event',end,**kwargs)
        event('button_release_event',end,**kwargs)

    def native_drag(start, end, modifier=None):
        """One OS mouse drag through the actual Tk window; never substitute generated callbacks on Windows."""
        from ctypes import byref, windll
        from ctypes.wintypes import POINT
        user = windll.user32; saved = POINT(); user.GetCursorPos(byref(saved))
        widget = app.graph_canvas.get_tk_widget()
        from .native_pointer_smoke import focus_pointer_window,screen_position
        observed=[]
        def observe(event):
            if event.guiEvent is not None and event.button==1:
                observed.append({'name':event.name,'inside_axes':event.inaxes is ax,'x':event.x,'y':event.y,'key':event.key})
        connections=[app.graph_canvas.mpl_connect(name,observe) for name in ('button_press_event','button_release_event')]
        def pump(seconds=.08):
            deadline = time.monotonic()+seconds
            while time.monotonic()<deadline:
                root.update(); time.sleep(.01)
        def screen(point):
            x,y = ax.transAxes.transform(point)
            return screen_position((widget.winfo_rootx(),widget.winfo_rooty()),widget.winfo_height(),(x,y),app.graph_canvas.device_pixel_ratio)
        held = False
        virtual_key = {'ctrl':0x11, 'shift':0x10}.get(modifier)
        try:
            owner=focus_pointer_window(root,widget,pump)
            user.SetCursorPos(*screen(start)); pump(.6)
            owner=focus_pointer_window(root,widget,pump)
            if virtual_key is not None:
                assert not user.GetAsyncKeyState(virtual_key) & 0x8000, 'Modifier already held before test'
                user.keybd_event(virtual_key,0,0,0);held=True;pump()
            user.mouse_event(2,0,0,0,0); pump()
            for fraction in (.2,.4,.6,.8,1.):
                user.SetCursorPos(*screen(np.asarray(start)+(np.asarray(end)-start)*fraction)); pump()
            user.mouse_event(4,0,0,0,0); pump()
        finally:
            user.mouse_event(4,0,0,0,0)
            if held:user.keybd_event(virtual_key,0,2,0)
            user.SetCursorPos(saved.x,saved.y)
            for connection in connections:app.graph_canvas.mpl_disconnect(connection)
        trace = 'native-pointer'+('-'+modifier if modifier else '')+'.json'
        (out/trace).write_text(json.dumps({'foreground_pid':owner,
            'device_pixel_ratio':app.graph_canvas.device_pixel_ratio,'events':observed},indent=2),encoding='utf-8')
        assert {event['name'] for event in observed if event['inside_axes']} == {'button_press_event','button_release_event'}, 'OS drag did not reach the actual drawing canvas.'
        if modifier:
            assert any(modifier in (event['key'] or '').replace('control','ctrl') for event in observed)

    # A preview is never a recipe, including a valid preview followed by an invalid release.
    choose_mode('rectangle')
    event('button_press_event',(.12,.16)); event('motion_notify_event',(.4,.4))
    assert SHAPES not in (run.style or {}) and not app.dirty
    event('button_release_event',(1.3,.4))
    assert SHAPES not in (run.style or {}) and not ax._tramastat_shapes

    choose_mode('arrow')
    if sys.platform == 'win32': native_drag((.15,.2),(.45,.4))
    else: drag((.15,.2),(.45,.4))
    assert len(run.style[SHAPES]) == 1 and run.style[SHAPES][0]['arrow_heads'] == 'end'
    assert app.shape_controller.mode == 'select' and app.dirty
    assert root.grab_current() is None
    choose_mode('rectangle'); drag((.5,.4),(.58,.55),key='control')
    assert len(run.style[SHAPES]) == 2, ('Ctrl square did not fit the plot', ax.bbox.bounds)
    choose_mode('ellipse'); drag((.15,.65),(.35,.85),key='shift')
    assert app.shape_controller.mode == 'ellipse'
    choose_mode('line'); drag((.55,.2),(.8,.35))
    assert len(run.style[SHAPES]) == 4

    # Move the arrow by its shaft, resize the end, nudge with a real Tk key, then delete and undo.
    choose_mode('select'); drag((.3,.3),(.35,.35))
    moved = deepcopy(run.style[SHAPES][0]); assert np.asarray(moved['points'])[0,0] > .19
    drag(moved['points'][1],(.6,.5))
    assert np.allclose(run.style[SHAPES][0]['points'][1],[.6,.5],atol=.015)
    widget = app.graph_canvas.get_tk_widget(); widget.focus_force(); root.update()
    before = deepcopy(run.style[SHAPES][0])
    widget.event_generate('<Shift-Right>'); root.update()
    assert run.style[SHAPES][0]['points'][0][0] > before['points'][0][0]
    count = len(run.style[SHAPES]); widget.event_generate('<Delete>'); root.update()
    assert len(run.style[SHAPES]) == count-1
    widget.event_generate('<Control-z>'); root.update(); assert len(run.style[SHAPES]) == count
    widget.event_generate('<Control-y>'); root.update(); assert len(run.style[SHAPES]) == count-1
    app.apply_worksheet_history(); root.update(); assert len(run.style[SHAPES]) == count

    # Modifier constraints operate in screen coordinates; exercise OS modifiers on Windows.
    for modifier, frozen_dimension in (('ctrl',1),('shift',0)):
        record = run.style[SHAPES][0]
        before_pixels = ax.transAxes.transform(record['points'])
        midpoint = np.mean(record['points'],axis=0)
        endpoint = midpoint+np.array([.025,.035])
        if sys.platform == 'win32':native_drag(midpoint,endpoint,modifier)
        else:drag(midpoint,endpoint,key=modifier)
        after_pixels = ax.transAxes.transform(run.style[SHAPES][0]['points'])
        np.testing.assert_allclose(after_pixels[:,frozen_dimension],before_pixels[:,frozen_dimension],atol=1e-6)
        assert np.all(after_pixels[:,1-frozen_dimension] > before_pixels[:,1-frozen_dimension]+1)
    before_pixels = ax.transAxes.transform(run.style[SHAPES][0]['points'])
    if sys.platform == 'win32':
        from ctypes import windll
        from .native_pointer_smoke import focus_pointer_window
        user=windll.user32;held=[]
        def key_pump(seconds=.08):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:root.update();time.sleep(.01)
        focus_pointer_window(root,widget,key_pump)
        try:
            for keycode in (0x11,0x27):
                assert not user.GetAsyncKeyState(keycode) & 0x8000, 'Nudge key already held before test'
                user.keybd_event(keycode,0,0,0);held.append(keycode)
            key_pump()
        finally:
            for keycode in reversed(held):user.keybd_event(keycode,0,2,0)
        key_pump()
    else:
        widget.focus_force();root.update();widget.event_generate('<Control-Right>');root.update()
    np.testing.assert_allclose(ax.transAxes.transform(run.style[SHAPES][0]['points'])-before_pixels,
                               [[10,0],[10,0]],atol=1e-6)

    # Enter opens the existing numerical editor; Cancel restores confirmed drawing without a new history step.
    app.shape_controller.selected = run.style[SHAPES][0]['id']
    confirmed = deepcopy(run.style); history_position = run.shape_history.position
    def cancel_editor(dialog):
        dialog.fields['stroke'].set('#ac2255'); assert dialog.preview(); dialog.cancel()
    kit.drive_dialog(ShapeEditor,cancel_editor)
    app.shape_controller.key('enter'); root.update()
    assert run.style == confirmed and run.shape_history.position == history_position

    pd.testing.assert_frame_equal(app.tables[title].raw,frame,check_dtype=False)
    assert (ax.get_xlim(),ax.get_ylim()) == original_limits[:2]
    np.testing.assert_array_equal(ax.dataLim.get_points(),original_limits[2])
    kit.capture(root,'window-canvas-shapes.png')

    # Screen-only selection handles must not appear in raster OR vector saved content.
    def rendered(fmt):
        buf = BytesIO()
        with rc_context({'svg.hashsalt':'canvas-smoke'}):
            fig.savefig(buf,format=fmt,metadata={'Date':None} if fmt=='svg' else {})
        return buf.getvalue()
    selected = {fmt:rendered(fmt) for fmt in ('svg','png')}
    choose_mode(None)
    for fmt, data in selected.items():
        actual = rendered(fmt)
        equivalent = _canonical_clip_ids(actual) == _canonical_clip_ids(data) if fmt=='svg' else actual==data
        if not equivalent:
            (out/('selected.'+fmt)).write_bytes(data)
            (out/('unselected.'+fmt)).write_bytes(actual)
        assert equivalent, 'Selection leaked into '+fmt

    # A sheet switch cancels an active preview and graph history remains independent of source edits.
    choose_mode('ellipse'); event('button_press_event',(.2,.2)); event('motion_notify_event',(.4,.4))
    app.show('data',title); root.update(); assert root.grab_current() is None
    assert run.style == confirmed and len(ax._tramastat_shapes) == 4
    app.show('graph',0); root.update(); app.apply_worksheet_history(); app.apply_worksheet_history(redo=True)
    assert run.style == confirmed
    app.path = project; assert app.save(); app.import_file(project); app.open_sheet(('graph',0)); wait()
    run = app.runs[0]; assert run.style == confirmed and not run.shape_history.changes
    app.show('data',title); app.edit_cell(0,1,'2.6'); wait()
    app.current_grid.active_cell = (2,1); app.toggle_exclusion(); wait()
    assert app.runs[0].style == confirmed
    app.show('graph',0); wait()
    for fmt in ('svg','png','pdf'):
        path = out / ('canvas.'+fmt)
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)): app.export()
        assert path.exists() and path.stat().st_size > 1000
    svg = ET.parse(out/'canvas.svg').getroot()
    groups = [e for e in svg.iter() if 'tramastat-shape-' in (e.get('id') or '')]
    assert len(groups) == 4
    def compose(dialog):
        dialog.name.set('Drawn objects'); dialog.columns.set('1')
        dialog.list.selection_clear(0,'end'); dialog.list.selection_set(0); dialog.add_selected()
    kit.drive_dialog(kit.LayoutDialog,compose); app.new_layout(); root.update()
    index=len(app.layouts)-1
    app.show('layout',index); app.recalculate_layout(index); wait(); app.show('layout',index)
    path=out/'canvas-layout.svg'
    with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(path)): app.export()
    layout=ET.parse(path).getroot()
    groups=[e for e in layout.iter() if 'tramastat-shape-' in (e.get('id') or '')]
    assert len(groups)==4 and not layout.findall('.//{http://www.w3.org/2000/svg}image')
    (out/'evidence.json').write_text(json.dumps({'os_pointer_drag':sys.platform=='win32',
        'horizontal_vertical_constraints':True,'ctrl_arrow_ten_pixels':True,
        'native_modifier_input':sys.platform=='win32',
        'shapes':confirmed[SHAPES], 'selection_free_svg_png':True,'save_reopen_recalculate':True},indent=2),encoding='utf-8')
