"""Real desktop acceptance of Duplicate family… and Save family as….

It drives the mapped widgets of the application (Family menu, navigator context menu, the dialog, the
worker, saving and exporting) in English and Italian on the theme and screen of the running process.
It does not simulate manual pointer or keyboard use and does not measure the system DPI.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import tkinter as tk
from unittest.mock import patch
from uuid import UUID

import numpy as np
import pandas as pd

from . import family_workflow_app, i18n, ui_theme
from .analysis_chain import ChainCancelled
from .data import Dataset, load_workspace, save_project
from .family_workflow_dialog import FamilyDialog
from .graph_language_smoke import drive_mapped_dialog
from .info import InfoSheet, info_contexts
from .pairwise_graph import PAIRED_COLUMNS, SECTION, drawn_brackets, section_record
from .presentation import Layout


def native_project():
    """Three synthetic tables: a chain with a formula, a plain fit, and a graph annotated by a test."""
    from .analysis_chain import ResultSource
    ids = [str(UUID(int=i)) for i in range(101, 110)]
    a = Dataset(pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]}),
                formulas={'Z': '=2*Y+INFO("Scale")'}, analyses=[
                    ('Transform', {'Variables': ['X', 'Z'], 'Operation': 'Absolute value'}),
                    ('Normalize', {'Variables': ['X', 'Z'], 'Method': 'Subtract first value'}),
                    ('Linear regression', {'X': 'X', 'Y': 'Z'}),
                    ('Histogram', {'Response': 'Y', 'Bins': 3})],
                graph_styles={2: {'title': 'A fit', 'xlabel': 'Dose', 'ylabel': 'Response',
                                  'axis': {'x': {'min': 0., 'max': 4., 'step': 1.}},
                                  'reference_lines': [{'axis': 'y', 'value': 5., 'label': 'Target'}]}})
    a.analysis_ids = dict(enumerate(ids[:4]))
    a.analysis_sources = {1: ResultSource(ids[0], 'Transformed'), 2: ResultSource(ids[1], 'Normalized')}
    b = Dataset(pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [3., 4., 5., 6.]}),
                analyses=[('Linear regression', {'X': 'X', 'Y': 'Y'})], analysis_ids={0: ids[4]})
    c = Dataset(pd.DataFrame({'A': [2., 3., 5., 6.], 'B': [1., 2., 3., 4.5]}), analyses=[
        ('Histogram', {'Response': 'A', 'Bins': 3}),
        ('Transform', {'Variables': ['A', 'B'], 'Operation': 'Absolute value'}),
        (PAIRED_COLUMNS, {'First': 'A', 'Second': 'B'}),
        ('Column graph', {'Variables': ['A', 'B'], SECTION: section_record(2, PAIRED_COLUMNS)})],
        analysis_ids=dict(enumerate(ids[5:9])))
    infos = [InfoSheet('A protocol', (('Scale', '1'), ('Protocol', 'Synthetic protocol')), 'Plan: example only.',
                       table='A', uid='a1' * 16, note_styles=((0, 4, 1),)),
             InfoSheet('Project details', (('Project code', 'SYNTHETIC'),), uid='b2' * 16)]
    tables = {'A': a, 'B': b, 'C': c}
    contexts = info_contexts(infos)
    for title, dataset in tables.items():
        dataset.info = contexts.get(title, contexts[None])
    layouts = [Layout('A and B', 2, [('A', 2), ('B', 0)]), Layout('B alone', 1, [('B', 0)]),
               Layout('Pairs', 1, [('C', 3)])]
    return tables, layouts, infos


def global_project():
    """Two tables that read one project-wide constant, and a layout that shows both fits."""
    info = InfoSheet('Shared scale', (('Scale', '3'),), uid='c3' * 16)
    contexts = info_contexts([info])
    tables = {name: Dataset(pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]}),
                            formulas={'Z': '=2*Y+INFO("Scale")'},
                            analyses=[('Linear regression', {'X': 'X', 'Y': 'Z'})],
                            analysis_ids={0: str(UUID(int=number))}, info=contexts[None])
              for number, name in enumerate(('G1', 'G2'), 120)}
    return tables, [Layout('Both fits', 2, [('G1', 0), ('G2', 0)])], [info]


def _frozen(app, titles):
    """Everything an original table keeps: any change made by a copy would show here."""
    return {title: (app.tables[title].raw.to_json(), sorted(app.tables[title].formulas.items()),
                    sorted(app.tables[title].excluded),
                    json.dumps(app.tables[title].analyses, sort_keys=True, default=str),
                    json.dumps({str(k): v for k, v in app.tables[title].graph_styles.items()}, sort_keys=True,
                               default=str),
                    sorted(app.tables[title].analysis_ids.items()),
                    sorted((k, str(v)) for k, v in app.tables[title].analysis_sources.items()))
            for title in titles}


def check_family_workflow(root, app, directory, tools):
    """``tools`` carries App, capture, messagebox, filedialog and the smoke's errors list."""
    out = Path(directory)/'family-workflow'
    out.mkdir(exist_ok=True)
    original_language, original_theme = i18n.active_language(), ui_theme._state.get('theme', 'standard')
    windows, report = [], {'screen': [root.winfo_screenwidth(), root.winfo_screenheight()],
                           'theme': original_theme, 'languages': {}}
    root.update()
    if not app.nav.winfo_ismapped():
        # The stand-alone run starts on the start page, where the navigator is hidden: open a sheet so that the
        # check at the end (the main window must come back as it was) has something to compare.
        app._add_tables({'Probe': pd.DataFrame({'X': [1., 2.], 'Y': [2., 3.]})})
        root.update()
    navigator_shown = app.nav.winfo_ismapped()
    assert navigator_shown, 'the navigator should be visible before the check'
    try:
        for code in ('en', 'it'):
            i18n.set_language(code)
            window = tk.Toplevel(root)
            instance = tools.App(window)
            instance.error = lambda error: tools.errors.append(str(error))
            windows.append(instance)
            for other in windows:
                if other is not instance and other.root.winfo_exists():
                    other.root.withdraw()
            root.withdraw()
            screen = root.winfo_screenwidth(), root.winfo_screenheight()
            window.geometry(f'{min(screen[0], 1560)}x{min(screen[1], 930)}+0+0')
            window.update()
            report['languages'][code] = _scenario(root, instance, out/code, tools, code)
        (out/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    finally:
        for instance in windows:
            instance.worker.shutdown(wait=False)
            instance.root.destroy()
        i18n.set_language(original_language)
        ui_theme.configure(root, original_theme)
        root.deiconify()
        root.update()  # let the map event arrive: the main window, and its navigator, must be visible again
    # The check hides the main window while it drives its own instances; it must leave it as it found it.
    assert app.nav.winfo_ismapped() == navigator_shown, 'the main window was not restored'


def _scenario(root, app, out, tools, code):
    out.mkdir(exist_ok=True)
    tr, errors = i18n.tr, tools.errors
    messagebox, filedialog = tools.messagebox, tools.filedialog
    found = {}

    # -- helpers --------------------------------------------------------------------------------

    def finish():
        deadline = time.monotonic() + 40
        while app.pending is not None:
            assert time.monotonic() < deadline, 'The worker did not finish'
            root.update()
            time.sleep(.02)
        root.update()
        assert not errors, errors

    def drive(action):
        def ready(dialog):
            try:
                action(dialog)
            except Exception as error:
                errors.append(f'FamilyDialog: {error!r}')
            if dialog.winfo_exists():
                dialog.cancel()
        drive_mapped_dialog(root, FamilyDialog, ready, errors, timeout=30)

    def run_index(title, slot):
        return next(i for i, run in enumerate(app.runs) if run.reference == (title, slot))

    def slope(title):
        run = next(run for run in app.runs if run.title == title and run.method == 'Linear regression')
        assert run.result is not None and run.calculation_error is None, (title, run.calculation_error)
        return float(run.result.tables['Regression'].loc['Slope', 'Value'])

    def inside(widget):
        root.update_idletasks()
        assert widget.winfo_viewable(), widget
        top = widget.winfo_toplevel()
        assert 0 <= widget.winfo_rootx() and widget.winfo_rootx() + widget.winfo_width() <= root.winfo_screenwidth()
        assert 0 <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= root.winfo_screenheight()
        assert widget.winfo_rootx() >= top.winfo_rootx() and widget.winfo_rooty() >= top.winfo_rooty()

    def counts(tables, analyses, layouts, infos):
        return tr('family.counts', tables=tables, analyses=analyses, layouts=layouts, infos=infos)

    def state():
        return (list(app.tables), len(app.runs), len(app.layouts), len(app.info_sheets), app.dirty, app.selected,
                app.path, len(app.history))

    def open_dialog(selected=None, *, via='menu', title='Family', label='Duplicate family…'):
        """Open the dialog the way the user does: the Family menu entry or the navigator context menu."""
        if selected is not None:
            app.open_sheet(selected)
            finish()
        if via == 'menu':
            popup, index = app.menu_entries[title, label]
            popup.invoke(index)
        else:
            node = next(node for node, ref in app.nodes.items() if ref == selected)
            before = app.selected
            app.update_nav_menu(node)
            assert str(app.nav_menu.entrycget(5, 'state')) == 'normal'
            app.nav_menu.invoke(5 if label == 'Duplicate family…' else 6)
            assert app.selected == before or app.selected != selected

    def duplicate(selected, name, *, include=None, via='menu', inspect=None):
        def action(dialog):
            if inspect:
                inspect(dialog)
            if include is not None:
                dialog.include_var.set(include)
                dialog.refresh()
            if name is not None:
                dialog.name_var.set(name)
            dialog.ok_button.invoke()
        drive(action)
        open_dialog(selected, via=via)
        finish()

    def preview_only(selected, check):
        if selected is not None:
            app.open_sheet(selected)
            finish()
        before = state()

        def action(dialog):
            check(dialog)
            dialog.cancel_button.invoke()
        drive(action)
        open_dialog()
        finish()
        assert state() == before, (state(), before)

    def text(dialog):
        return dialog.preview.get('1.0', 'end')

    # -- project ---------------------------------------------------------------------------------

    tables, layouts, infos = native_project()
    project = out/'native.alab'
    save_project(project, tables, layouts=layouts, info_sheets=infos)
    app.import_file(project)
    finish()
    assert list(app.tables) == ['A', 'B', 'C'] and not app.dirty
    assert app.selected == ('data', 'A')
    for title, kind in (('Family', 'Duplicate family…'), ('Family', 'Save family as…')):
        assert (title, kind) in app.menu_entries
    popup, index = app.menu_entries['Family', 'Duplicate family…']
    assert popup.entrycget(index, 'label') == tr('command.duplicate_family')
    app.open_sheet(('result', run_index('A', 2)))
    finish()
    app.open_sheet(('result', run_index('B', 0)))
    finish()
    assert abs(slope('A') - 4.) < 1e-12 and abs(slope('B') - 1.) < 1e-12
    originals = _frozen(app, ['A', 'B', 'C'])
    app.open_sheet(('data', 'A'))
    base_state = state()

    # -- the dialog: widgets, name errors, previews that change nothing -------------------------------

    def taken(dialog):
        for widget in (dialog.ok_button, dialog.cancel_button, dialog.name_entry, dialog.preview,
                       dialog.include_check):
            inside(widget)
        assert counts(1, 4, 1, 1) in text(dialog), text(dialog)
        assert tr('family.note.shared_panels', count=1) in text(dialog)
        assert tr('family.note.global_info') in text(dialog)
        assert dialog.error_var.get() == ''
        dialog.name_var.set('B')
        assert dialog.error_var.get() == tr('family.error.name-taken', name='B')
        inside(dialog.error_label)
        dialog.ok_button.invoke()
        assert dialog.winfo_exists() and dialog.error_var.get() == tr('family.error.name-taken', name='B')
        tools.capture(dialog, f'window-family-name-taken-{code}.png')
        dialog.name_var.set('')
        assert dialog.error_var.get() == tr('family.error.name-empty.name')
        dialog.name_var.set('Bad\nname')
        assert dialog.error_var.get() == tr('family.error.name-invalid')
        dialog.name_var.set('November')
        assert dialog.error_var.get() == ''
        assert 'A → November' in text(dialog), text(dialog)
        assert 'A and B → November and B' in text(dialog), text(dialog)
        assert 'A protocol → November protocol' in text(dialog), text(dialog)
        tools.capture(dialog, f'window-family-preview-data-{code}.png')

    preview_only(None, taken)
    assert state() == base_state

    def graph_preview(dialog):
        assert counts(1, 3, 1, 1) in text(dialog), text(dialog)
        assert 'Histogram' not in text(dialog)
        dialog.include_var.set(False)
        dialog.refresh()
        assert counts(1, 3, 0, 1) in text(dialog), text(dialog)
        assert tr('family.note.shared_panels', count=1) not in text(dialog)
        assert dialog.error_var.get() == ''

    preview_only(('graph', run_index('A', 2)), graph_preview)

    def layout_preview(dialog):
        assert counts(2, 4, 1, 1) in text(dialog), text(dialog)
        assert dialog.include_check.instate(['disabled']) and dialog.include_var.get()
        assert tr('family.note.shared_panels', count=1) not in text(dialog)
        dialog.name_var.set('Repeat ')
        assert dialog.error_var.get() == ''
        assert 'Repeat A' in text(dialog) and 'Repeat B' in text(dialog), text(dialog)
        tools.capture(dialog, f'window-family-preview-layout-{code}.png')

    preview_only(('layout', 0), layout_preview)

    # A refused name or a cancelled dialog changes nothing; an Info sheet linked to the table works too.
    def info_preview(dialog):
        assert counts(1, 4, 1, 1) in text(dialog), text(dialog)
    info_uid = next(uid for uid, sheet in app.info_sheets.items() if sheet.table == 'A')
    preview_only(('info', info_uid), info_preview)
    global_uid = next(uid for uid, sheet in app.info_sheets.items() if sheet.table is None)
    app.open_sheet(('info', global_uid))
    before = state()
    with patch.object(messagebox, 'showinfo') as explained:
        popup, index = app.menu_entries['Family', 'Duplicate family…']
        popup.invoke(index)
    assert explained.called and tr('family.error.global-info') in explained.call_args.args[1]
    assert state() == before and not any(isinstance(w, FamilyDialog) for w in app.root.winfo_children())

    # -- duplicate A as November: independence, calculation, edits and undo ----------------------------

    app.open_sheet(('data', 'A'))
    duplicate(None, 'November')
    assert 'November' in app.tables and app.dirty
    assert app.selected == ('data', 'November'), app.selected
    assert _frozen(app, ['A', 'B', 'C']) == originals
    novem = [run for run in app.runs if run.title == 'November']
    assert [run.method for run in novem] == ['Transform', 'Normalize', 'Linear regression', 'Histogram']
    assert all(run.result is None for run in novem)
    assert {run.uid for run in novem}.isdisjoint({run.uid for run in app.runs if run.title != 'November'})
    assert novem[1].source.analysis_id == novem[0].uid and novem[2].source.analysis_id == novem[1].uid
    assert [layout.name for layout in app.layouts][-1] == 'November and B'
    assert app.layouts[-1].panels == [('November', 2), ('B', 0)] and app.layouts[0].panels == [('A', 2), ('B', 0)]
    assert any(sheet.table == 'November' and sheet.title == 'November protocol' for sheet in app.info_sheets.values())
    assert app.status.get().startswith(tr('family.duplicated', tables=1, analyses=4, layouts=1, infos=1)[:30])
    found['status'] = app.status.get()

    app.open_sheet(('result', run_index('November', 2)))
    finish()
    assert abs(slope('November') - 4.) < 1e-12
    assert app.tables['November'].graph_styles[2]['title'] == 'A fit'
    assert app.tables['November'].graph_styles[2]['reference_lines'] == tables['A'].graph_styles[2]['reference_lines']
    app.show('data', 'November')
    app.edit_cell(1, 1, '4')
    finish()
    assert abs(slope('November') - 3.8) < 1e-12 and abs(slope('A') - 4.) < 1e-12
    app.show('data', 'November')
    app.current_grid.select((1, 1))
    app.toggle_exclusion()
    finish()
    assert abs(slope('November') - 4.) < 1e-12 and abs(slope('A') - 4.) < 1e-12
    app.show('data', 'November')
    app.apply_worksheet_history()
    finish()
    assert abs(slope('November') - 3.8) < 1e-12
    assert _frozen(app, ['A', 'B', 'C']) == originals
    found['slopes'] = {'copy_edited': 3.8, 'copy_excluded': 4., 'original': 4.}

    # -- Info: a local constant of the copy ----------------------------------------------------------

    sheet = next(sheet for sheet in app.info_sheets.values() if sheet.table == 'November')
    assert sheet.note_styles == ((0, 4, 1),)
    assert app.tables['November'].frame()['Z'].iloc[0] == 3.
    app.change_info(replace(sheet, fields=(('Scale', '5'), ('Protocol', 'Synthetic protocol'))))
    finish()
    assert app.tables['November'].frame()['Z'].iloc[0] == 7. and app.tables['A'].frame()['Z'].iloc[0] == 3.
    assert abs(slope('November') - 3.8) < 1e-12

    # -- the graph of C: the annotation follows the copy of the test ------------------------------------

    app.open_sheet(('graph', run_index('C', 3)))
    finish()
    original_brackets = repr(drawn_brackets(app.runs[run_index('C', 3)].result.figure))
    assert original_brackets != '[]'
    duplicate(('graph', run_index('C', 3)), 'Repeat ', via='context')
    assert 'Repeat C' in app.tables and [m for m, _ in app.tables['Repeat C'].analyses] == [PAIRED_COLUMNS,
                                                                                            'Column graph']
    assert app.tables['Repeat C'].analyses[1][1][SECTION]['Source slot'] == 0
    assert app.tables['C'].analyses[3][1][SECTION]['Source slot'] == 2
    assert 'Repeat C' in app.tables and app.selected[0] == 'graph'
    finish()
    copied = app.runs[run_index('Repeat C', 1)]
    assert copied.result is not None and copied.calculation_error is None
    assert repr(drawn_brackets(copied.result.figure)) == original_brackets
    app.show('data', 'Repeat C')
    app.edit_cell(0, 0, '12')
    finish()
    assert repr(drawn_brackets(app.runs[run_index('Repeat C', 1)].result.figure)) != original_brackets
    assert repr(drawn_brackets(app.runs[run_index('C', 3)].result.figure)) == original_brackets
    assert _frozen(app, ['A', 'B', 'C']) == originals

    # -- prefix copy of a chain, then save, reopen and open the final graph first --------------------

    duplicate(('graph', run_index('A', 2)), 'Again ', include=False)
    finish()
    assert 'Again A' in app.tables and not any(layout.name.startswith('Again') for layout in app.layouts)
    labels = {run.slot: run.name for run in app.runs if run.title == 'Again A'}
    assert labels == {0: 'Again Transform of A', 1: 'Again Normalize of Transformed',
                      2: 'Again Linear regression of Normalized'}, labels
    assert [run.name for run in app.runs if run.title == 'A'][0] == 'Transform of A'
    saved = out/'saved.alab'
    app.path = saved
    assert app.save()
    stored = json.loads(saved.read_text(encoding='utf-8'))
    assert stored['version'] == 3
    assert [table['analysis_labels'] for table in stored['tables'] if table['title'] == 'Again A'] == [
        {'0': 'Again Transform of A', '1': 'Again Normalize of Transformed',
         '2': 'Again Linear regression of Normalized'}]
    app.import_file(saved)
    assert all(run.result is None for run in app.runs)
    last = run_index('Again A', 2)
    app.open_sheet(('graph', last))
    finish()
    assert abs(slope('Again A') - 4.) < 1e-12
    assert {run.slot: run.name for run in app.runs if run.title == 'Again A'} == labels
    assert app.runs[last].source is not None and app.runs[last].result.figure is not None
    found['reopened_chain_slope'] = 4.

    # -- the only Info sheet is project-wide: local snapshots --------------------------------------------

    gtables, glayouts, ginfos = global_project()
    gpath = out/'global.alab'
    save_project(gpath, gtables, layouts=glayouts, info_sheets=ginfos)
    app.import_file(gpath)
    finish()
    app.open_sheet(('layout', 0))
    finish()

    def snapshot(dialog):
        assert tr('family.note.snapshot') in text(dialog), text(dialog)
        assert counts(2, 2, 1, 2) in text(dialog), text(dialog)
        dialog.name_var.set('Repeat ')
        tools.capture(dialog, f'window-family-snapshot-{code}.png')
        dialog.ok_button.invoke()
    drive(snapshot)
    open_dialog(None)
    finish()
    assert list(app.tables) == ['G1', 'G2', 'Repeat G1', 'Repeat G2']
    local = {sheet.table: sheet for sheet in app.info_sheets.values() if sheet.table}
    assert set(local) == {'Repeat G1', 'Repeat G2'} and len(app.info_sheets) == 3
    assert app.tables['Repeat G1'].frame()['Z'].iloc[0] == 5.
    app.change_info(replace(local['Repeat G1'], fields=(('Scale', '9'),)))
    finish()
    assert [app.tables[title].frame()['Z'].iloc[0] for title in ('G1', 'G2', 'Repeat G1', 'Repeat G2')] == [
        5., 5., 11., 5.]

    # -- Save family as…: with and without layouts, cancel, the current path ------------------------------

    app.import_file(project)
    finish()
    app.open_sheet(('data', 'A'))
    before = state()

    def chooser(path):
        return patch.object(filedialog, 'asksaveasfilename', return_value=str(path) if path else '')

    def save_family(name, include, selected=None, *, via='menu', accept=True):
        def action(dialog):
            dialog.include_var.set(include)
            dialog.refresh()
            tools.capture(dialog, f'window-family-save-{"layouts" if include else "plain"}-{code}.png')
            (dialog.ok_button if accept else dialog.cancel_button).invoke()
        drive(action)
        with chooser(name):
            open_dialog(selected, via=via, label='Save family as…')
            finish()

    save_family(out/'family-layouts.alab', True, via='context', selected=('data', 'A'))
    assert state()[:5] == before[:5] and state()[6] == before[6]
    reopened, layouts_in, infos_in = load_workspace(out/'family-layouts.alab', include_info=True)
    assert list(reopened) == ['A', 'B'] and [layout.name for layout in layouts_in] == ['A and B']
    assert {sheet.title for sheet in infos_in} == {'A protocol'}
    save_family(out/'family-plain.alab', False, selected=('data', 'A'))
    reopened, layouts_in, infos_in = load_workspace(out/'family-plain.alab', include_info=True)
    assert list(reopened) == ['A'] and layouts_in == []
    assert state() == before or state()[:6] == before[:6]
    keep = hashlib.sha256((out/'family-plain.alab').read_bytes()).hexdigest()
    with chooser(None):
        popup, index = app.menu_entries['Family', 'Save family as…']
        drive(lambda dialog: dialog.ok_button.invoke())
        popup.invoke(index)
        finish()
    assert state()[:6] == before[:6]
    current = out/'native.alab'
    app.path = current
    digest = hashlib.sha256(current.read_bytes()).hexdigest()
    with chooser(current), patch.object(app, 'error') as refused:
        drive(lambda dialog: dialog.ok_button.invoke())
        popup.invoke(index)
        finish()
    assert refused.called and tr('family.error.current-path') in refused.call_args.args[0]
    assert hashlib.sha256(current.read_bytes()).hexdigest() == digest
    link = out/'current-link.alab'
    link.unlink(missing_ok=True)
    os.link(current, link)
    aliases = [('hard_link', link)]
    symbolic = out/'current-symbolic.alab'
    symbolic.unlink(missing_ok=True)
    try:
        symbolic.symlink_to(current.name)
    except OSError as error:
        if os.name != 'nt' or error.winerror != 1314:
            raise
        found['symbolic_link'] = 'NOT AVAILABLE: Windows account lacks symbolic-link creation privilege.'
    else:
        aliases.append(('symbolic_link', symbolic))
    for kind, alias in aliases:
        with chooser(alias), patch.object(app, 'error') as refused:
            drive(lambda dialog: dialog.ok_button.invoke())
            popup.invoke(index)
            finish()
        assert refused.called and hashlib.sha256(current.read_bytes()).hexdigest() == digest
        found[kind] = 'PASS: current project overwrite refused.'
    assert keep == hashlib.sha256((out/'family-plain.alab').read_bytes()).hexdigest()

    # The saved family opens on its own, in a project of its own.
    original_key = app.active_project
    assert app.open_document(out/'family-layouts.alab')
    assert app.active_project != original_key and list(app.tables) == ['A', 'B'] and not app.dirty
    app.open_sheet(('layout', 0))
    finish()
    assert app.layout_figure is not None
    assert abs(slope('A') - 4.) < 1e-12 and abs(slope('B') - 1.) < 1e-12
    assert app.switch_project(original_key) and list(app.tables) == ['A', 'B', 'C']

    # -- exports of the copy: CSV, PNG, SVG, PDF --------------------------------------------------------

    app.import_file(saved)
    finish()
    copied_graph = run_index('Again A', 2)
    app.open_sheet(('graph', copied_graph))
    finish()
    from PIL import Image

    def export(selected, name):
        app.open_sheet(selected)
        finish()
        target = out/name
        with patch.object(filedialog, 'asksaveasfilename', return_value=str(target)):
            app.export()
        finish()
        return target

    original_png = export(('graph', run_index('A', 2)), 'original.png')
    copy_png = export(('graph', copied_graph), 'copy.png')
    assert Image.open(original_png).size == Image.open(copy_png).size
    svg = export(('graph', copied_graph), 'copy.svg').read_text(encoding='utf-8')
    assert 'A fit' in svg and 'Dose' in svg and 'Target' in svg
    assert export(('graph', copied_graph), 'copy.pdf').read_bytes().startswith(b'%PDF')
    csv = export(('result', copied_graph), 'copy.csv').read_text(encoding='utf-8')
    assert 'Slope' in csv
    found['exports'] = ['png', 'svg', 'pdf', 'csv']

    # -- a copy is refused while the worker is busy; a running copy can be cancelled whole ------------------

    app.open_sheet(('data', 'A'))
    pause = threading.Event()
    real_compute = app.compute

    def slow(*args, **kwargs):
        pause.wait(2)
        return real_compute(*args, **kwargs)

    before = state()
    with patch.object(app, 'compute', side_effect=slow):
        app.recalculate(run_index('A', 3))
        assert app.pending is not None
        with patch.object(app, 'error') as refused:
            app.duplicate_family(('data', 'A'))
            app.save_family_as(('data', 'A'))
        assert refused.call_count == 2 and refused.call_args.args[0] == tr('family.wait')
        assert not app.prepare_project_change()
        pause.set()
        finish()
    assert list(app.tables) == before[0] and len(app.runs) == before[1]

    seen = []
    real_duplicate = family_workflow_app.duplicate_family

    def endless(*args, cancel, **kwargs):
        seen.append(threading.current_thread().name)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise ChainCancelled
            time.sleep(.01)
        return real_duplicate(*args, cancel=cancel, **kwargs)

    state_before = state()
    with patch.object(family_workflow_app, 'duplicate_family', endless):
        def start(dialog):
            dialog.name_var.set('Slow copy')
            dialog.ok_button.invoke()
        drive(start)
        app.duplicate_family(('data', 'A'))
        deadline = time.monotonic() + 10
        while not seen and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        assert seen and seen[0].startswith('Trama') and app.pending is not None
        root.update()
        assert app.cancel_button.winfo_manager() == 'pack' and app.cancel_button.winfo_ismapped()
        app.cancel_calculation()
        finish()
    assert state() == state_before and 'Slow copy' not in app.tables
    assert app.status.get() == tr('family.cancelled')
    found['cancelled_on_worker'] = seen[0]

    # A copy that fails after the project was valid adds nothing and says why.
    def failing(*args, **kwargs):
        raise ValueError('synthetic failure')
    with patch.object(family_workflow_app, 'duplicate_family', failing), patch.object(app, 'error') as failed:
        drive(lambda dialog: (dialog.name_var.set('Broken'), dialog.ok_button.invoke()))
        app.duplicate_family(('data', 'A'))
        finish()
    assert failed.called and 'synthetic failure' in failed.call_args.args[0] and 'Broken' not in app.tables
    assert state() == state_before
    assert not errors, errors
    return found
