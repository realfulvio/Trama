"""Real modal editor page, focus, geometry and cancelled-preview checks."""
from copy import deepcopy
import json

import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .graph_shape_dialog import GraphShapesDialog, ShapeEditor
from .graph_shapes import SHAPES


def check_shape_editor_pages(kit):
    app,root,wait=kit.app,kit.root,kit.wait_for_calculation
    out=kit.directory/'object-editor-pages';out.mkdir(exist_ok=True)
    path=out/'editor-pages.alab'
    save_project(path,{'Editor data':Dataset(pd.DataFrame({'X':[1.,2,3,4],'Y':[2.,4.1,5.9,8.]}),
                  analyses=[('Linear regression',{'X':'X','Y':'Y'})])})
    app.import_file(path);app.open_sheet(('graph',0));wait();app.dirty=False
    previous=i18n.active_language();dimensions={}
    try:
        for language in ('en','it'):
            i18n.set_language(language)
            def parent(dialog):
                def editor_action(editor):
                    editor.notebook.select(editor.pages['position'])
                    editor.ok_button.focus_force();editor.update()
                    editor.fields['width'].set('0');editor.ok_button.invoke();editor.update()
                    assert editor.winfo_exists() and editor.result is None
                    assert editor.notebook.select()==str(editor.pages['appearance'])
                    assert editor.focus_lastfor() is editor.widgets['width']
                    editor.fields['width'].set('1,5')
                    editor.fields['x2'].set('bad coordinate');editor.ok_button.invoke();editor.update()
                    assert editor.notebook.select()==str(editor.pages['position'])
                    assert editor.focus_lastfor() is editor.widgets['x2']
                    if language=='it':kit.capture(editor,'window-object-position-error-066.png')
                    editor.fields['x2'].set('0,8');assert editor.preview()
                    if language=='it':kit.capture(editor,'window-object-position-066.png')
                    editor.notebook.select(editor.pages['appearance']);editor.update()
                    dimensions[language]=[editor.winfo_width(),editor.winfo_height()]
                    assert editor.winfo_width()<=1024 and editor.winfo_height()<=768
                    bottom=editor.winfo_rooty()+editor.winfo_height()
                    for button in (editor.preview_button,editor.ok_button,editor.cancel_button):
                        assert button.winfo_viewable() and button.winfo_rooty()+button.winfo_height()<=bottom
                    if language=='it':kit.capture(editor,'window-object-appearance-066.png')
                    editor.cancel()
                kit.drive_dialog(ShapeEditor,editor_action);dialog.add();dialog.cancel()
            kit.drive_dialog(GraphShapesDialog,parent);app.edit_graph_shapes();root.update()
            assert not app.dirty and SHAPES not in (app.runs[0].style or {})
            assert not app.runs[0].result.figure.axes[0]._tramastat_shapes
        (out/'evidence.json').write_text(json.dumps({'dialog_dimensions':dimensions,'cross_page_focus':True,
               'cancel_unchanged':True},indent=2),encoding='utf-8')
    finally:i18n.set_language(previous)
