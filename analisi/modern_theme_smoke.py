"""Portable acceptance of the optional Modern theme on real application widgets."""
from copy import deepcopy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from .theme_preferences import ThemeDialog, load_theme, save_theme
from .ui_shell import ModernRibbon
from .graph_language_smoke import drive_mapped_dialog


def check_modern_theme(root, app, directory, tools):
    assert ui_theme.is_modern(), 'Start with the Modern theme selected in isolated preferences.'
    assert isinstance(app.ribbon, ModernRibbon)
    large = root.winfo_screenwidth() >= 1600 and root.winfo_screenheight() >= 1000
    # Tk sizes describe the client; account for the Windows frame and taskbar.
    from .correlation_details_smoke import _client
    requested = (1560, 930) if large else (1000, 640)
    width, height = _client(root, (root.winfo_screenwidth(), root.winfo_screenheight()), requested)
    root.geometry(f'{width}x{height}+0+0')
    root.update()
    out = directory / 'modern-theme'; out.mkdir(exist_ok=True)
    original_language = i18n.active_language()
    def capture(window, name):
        tools.capture(window, name)
        path=directory/name
        if path.exists():path.replace(out/name)
    frame = pd.DataFrame({
        'X':[.01,.03,.1,.3,1.,3.,10.],
        'Control [1]':[2.1,3.2,7.8,18.9,44.2,78.7,96.1],
        'Control [2]':[2.4,3.5,8.3,19.4,46.9,80.1,97.],
        'Control [3]':[2.3,3.2,8.1,19.1,45.5,79.2,96.4],
        'Treatment [1]':[1.4,2.,4.6,11.2,28.1,62.7,89.4],
        'Treatment [2]':[1.3,2.1,5.1,12.5,30.4,64.8,90.1],
        'Treatment [3]':[1.6,2.4,4.8,11.9,29.2,63.9,89.7],
    })
    frame.attrs['table_format']='XY'
    app._add_tables({'Dose response':frame})
    options={'X':'X','Y columns':['Control [1]','Treatment [1]'],
             'Series style':{'Control [1]':'Line and points','Treatment [1]':'Line and points'},
             'Series color':{'Control [1]':'#00877f','Treatment [1]':'#ef806d'}}
    run=tools.Run('XY series','Dose response',options)
    run.style={'title':'Dose response','xlabel':'Concentration (µM)','ylabel':'Response (%)',
               'xscale':'log','legend':'upper left'}
    app.add_result(run,app.compute(run,frame))
    app.show('data','Dose response');root.update()
    ws=app.modern_workspace
    assert ws and ws.canvas and ws.figure is not run.result.figure
    assert not app.nav.exists('section:Family')
    app.search.set('Dose');root.update();assert app.nav.exists('section:Search results')
    app.search.set('');root.update();assert not app.nav.exists('section:Search results')
    original=run.result.figure
    original_size=original.get_size_inches().copy();original_dpi=original.dpi
    original_xlabel=original.axes[0].get_xlabel()
    app.current_grid.select_block(2,1,5,3)
    root.update()
    native_geometry = None
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        frame, work, tray = wintypes.RECT(), wintypes.RECT(), wintypes.RECT()
        handle = wintypes.HWND(int(root.wm_frame(), 0))
        assert ctypes.windll.dwmapi.DwmGetWindowAttribute(handle, 9, ctypes.byref(frame), ctypes.sizeof(frame)) == 0
        assert user.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)
        user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user.FindWindowW.restype = wintypes.HWND
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        bar = user.FindWindowW('Shell_TrayWnd', None)
        assert work.left <= frame.left < frame.right <= work.right
        assert work.top <= frame.top < frame.bottom <= work.bottom
        tray_values = None
        if bar and user.IsWindowVisible(bar) and user.GetWindowRect(bar, ctypes.byref(tray)):
            tray_values = [tray.left, tray.top, tray.right, tray.bottom]
            assert (min(frame.right, tray.right) <= max(frame.left, tray.left)
                    or min(frame.bottom, tray.bottom) <= max(frame.top, tray.top)), 'Window overlaps taskbar'
        native_geometry = {'frame':[frame.left,frame.top,frame.right,frame.bottom],
                           'work_area':[work.left,work.top,work.right,work.bottom],
                           'taskbar':tray_values}
    capture(root,'workspace-modern-startup.png')
    for language in ('en','it'):
        i18n.set_language(language)
        app.show('data','Dose response');root.update();ws=app.modern_workspace
        ws.sidebar_wanted.set(True);ws.toggle_sidebar();root.update()
        inspector=ws.inspector
        inspector.vars['xlabel'].set('Preview only')
        inspector._now('xlabel');root.update()
        assert ws.figure.axes[0].get_xlabel()=='Preview only'
        assert original.axes[0].get_xlabel()==original_xlabel
        inspector.discard();assert ws.figure.axes[0].get_xlabel()==original_xlabel
        inspector.vars['xmin'].set('0')
        inspector.vars['xmax'].set('10')
        inspector._now('xrange');root.update()
        assert inspector.errors and not inspector.apply()  # zero on a log axis
        inspector.discard()
        capture(root,'workspace-modern-'+language+'.png')
        np.testing.assert_array_equal(original.get_size_inches(),original_size)
        assert original.dpi==original_dpi
    inspector.vars['xlabel'].set('Confirmed concentration (µM)')
    inspector._now('xlabel');assert inspector.apply()
    assert run.style['xlabel']=='Confirmed concentration (µM)'
    assert app.tables[run.title].graph_styles[run.slot]==run.style
    # Save/export use the source figure; resizing the preview has not resized it.
    for suffix in ('png','svg','pdf'):
        original.savefig(out/f'confirmed-source.{suffix}')
    run.result.tables['Series values'].to_csv(out/'series.csv',index=False)
    app.path=out/'roundtrip.alab';assert app.save()
    before=run.result
    app.edit_cell(0,1,'3.1');tools.wait_for_calculation();root.update()
    assert run.result is not before
    assert app.modern_workspace._result_identity==(id(run),id(run.result))
    app.current_grid.active_cell=(1,1);app.toggle_exclusion();tools.wait_for_calculation();root.update()
    assert app.modern_workspace.canvas is not None
    app.apply_worksheet_history();tools.wait_for_calculation()
    app.show('data','Dose response');ws=app.modern_workspace
    ws.preview_wanted.set(False);ws.toggle_preview();assert ws.canvas is None
    ws.preview_wanted.set(True);ws.toggle_preview();root.update();assert ws.canvas is not None
    app.open_document(str(out/'roundtrip.alab'));app.show('data','Dose response')
    app.recalculate(0);tools.wait_for_calculation();root.update()
    assert app.runs[0].style['xlabel']=='Confirmed concentration (µM)'
    assert app.modern_workspace.figure.axes[0].get_xlabel()=='Confirmed concentration (µM)'
    # Preference chooser: Cancel does not switch; OK stores for a future launch only.
    pref=out/'preferences.json';save_theme(pref,'modern')
    def cancel(dialog):
        dialog.choice.set('standard');dialog.cancel()
    drive_mapped_dialog(root,ThemeDialog,cancel,tools.errors);ThemeDialog(root,pref,error=app.error)
    assert load_theme(pref)=='modern'
    def apply(dialog):
        dialog.choice.set('standard');capture(dialog,'theme-chooser.png')
    tools.drive_dialog(ThemeDialog,apply);ThemeDialog(root,pref,error=app.error)
    assert load_theme(pref)=='standard' and ui_theme.is_modern()
    i18n.set_language(original_language)
    (out/'checks.json').write_text(json.dumps({'status':'PASS','theme':'modern',
      'screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
      'native_geometry':native_geometry,
      'checks':['private Figure isolation','original size and DPI preserved','Inspector preview/discard/apply',
                'invalid log limits','EN/IT workspace','preference Cancel/OK','edit/exclusion/undo',
                'collapse/reopen preview','save/reopen/recalculate','CSV/PNG/SVG/PDF source export',
                'clean navigator and search']},indent=2))
