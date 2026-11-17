"""Desktop smoke check for Edit → Language…, kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_language` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=language python tramastat.py --smoke DIR``.

The check writes its preference under ``DIR/config`` (APPDATA or XDG_CONFIG_HOME), opens the real dialog,
then starts further App instances on the same configuration to stand in for the next launch.
"""
import json
import os
from pathlib import Path
import shutil
import time
import tkinter as tk
from tkinter import simpledialog, ttk
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from .language_dialog import LanguageDialog
from .table_setup import TEMPLATES, NewTableDialog, TableSetup

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "data" / "i18n"
MENUS_EN = ["File", "Edit", "View", "Insert", "Analyze", "Change", "Arrange", "Family", "Tools", "Settings"]
MENUS_IT = ["File", "Modifica", "Visualizza", "Inserisci", "Analisi", "Cambia", "Disponi", "Famiglia", "Strumenti", "Impostazioni"]
PROJECT = "Misurazioni {A} – città.alab"
SHORTCUTS = ("<Control-o>", "<Control-n>", "<Control-s>", "<Control-Shift-N>", "<Control-w>", "<Control-f>")


def check_language(root, app, directory, tools):
    """``tools`` carries App, AnalysisDialog, TextImportDialog, LayoutDialog, capture, drive_dialog,
    pick_method, messagebox, filedialog and the smoke's errors list."""
    config = directory / "config"
    shutil.rmtree(config, ignore_errors=True)
    original_language = i18n.active_language()
    original_theme = 'modern' if ui_theme.is_modern() else 'standard'
    windows = []
    try:
        with patch.dict(os.environ, {"APPDATA": str(config), "XDG_CONFIG_HOME": str(config)}):
            _check_language(root, app, directory, tools, windows)
    finally:
        for instance in windows:
            instance.worker.shutdown(wait=False)
            instance.root.destroy()
        i18n.set_language(original_language)
        ui_theme.configure(root, original_theme)
        root.deiconify()


def _check_language(root, app, directory, tools, windows):
    errors = tools.errors
    config = directory / "config"
    path = i18n.config_path()
    folder = "TramaStat" if os.name == "nt" else "tramastat"
    assert path == config / folder / "preferences.json", path

    def start(language):
        """A new instance reading the language like main() does."""
        i18n.set_language(language)
        window = tk.Toplevel(root)
        instance = tools.App(window)
        instance.error = lambda error: errors.append(str(error))
        windows.append(instance)
        window.update()
        return instance

    def front(instance):
        for other in windows:
            if other is not instance and other.root.winfo_exists():
                other.root.withdraw()
        instance.root.deiconify()
        instance.root.geometry("1010x700+0+0")
        instance.root.lift()
        instance.root.update()

    def wait(instance):
        deadline = time.monotonic() + 30
        while instance.pending is not None:
            if time.monotonic() > deadline:
                raise TimeoutError("Analysis did not complete")
            root.update()
            time.sleep(.02)
        assert not errors, errors

    def find(parent, kind):
        for child in parent.winfo_children():
            if isinstance(child, kind):
                return child
            found = find(child, kind)
            if found is not None:
                return found
        return None

    def with_language_dialog(owner, action):
        """Open the real dialog from the Edit menu command and run action on it (action closes it)."""
        def enter():
            dialog = find(owner.root, LanguageDialog)
            if dialog is None:
                errors.append("Language dialog did not open")
                return
            try:
                action(dialog)
            except Exception as error:  # report after the modal loop, never leave the dialog open
                errors.append(f"Language dialog: {error!r}")
            if dialog.winfo_exists():
                dialog.cancel()

        owner.root.after(200, enter)
        return owner.choose_language()

    def menu_labels(instance):
        menu = instance.menu
        return [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)
                if menu.type(index) == "cascade"]

    def menu_entries(instance):
        result = []
        for index in range(instance.menu.index("end") + 1):
            if instance.menu.type(index) != "cascade":
                continue
            popup = instance.root.nametowidget(instance.menu.entrycget(index, "menu"))
            result.append([(popup.entrycget(item, "label"), popup.entrycget(item, "accelerator"))
                           for item in range(popup.index("end") + 1)])
        return result

    def ribbon_titles(instance):
        return [pane.winfo_children()[0].cget("text") for pane in instance.ribbon.winfo_children()
                if isinstance(pane, ttk.Frame) and pane.winfo_children()
                and isinstance(pane.winfo_children()[0], ttk.Label)]

    def section_texts(instance):
        return [instance.nav.item(node, "text") for node in instance.nav.get_children()]

    root.withdraw()

    # 1. The running instance in English: Cancel, Esc and a failed write leave the preference alone.
    english = start("en")
    front(english)
    assert i18n.load_language(path) == "en" and not path.exists()
    assert menu_labels(english) == MENUS_EN, menu_labels(english)
    assert "Theme…" in dict(menu_entries(english)[-1])
    edit = dict(menu_entries(english)[1])
    assert edit["Language…"] == "" and edit["Paste Special…"] == "Ctrl+Shift+V", edit
    english.create_worksheet(TEMPLATES[0], True)
    english.dirty = True
    english.status.set("before")

    def cancel(dialog):
        assert dialog.title() == "Language / Lingua", dialog.title()
        assert [button.cget("text") for button in dialog.buttons.values()] == ["English", "Italiano"]
        assert dialog.choice.get() == "en"
        dialog.choice.set("it")
        dialog.cancel()

    assert with_language_dialog(english, cancel) is None
    assert not errors, errors
    assert not path.exists() and english.dirty and english.status.get() == i18n.translate("en", "language.unchanged")

    def escape(dialog):
        dialog.choice.set("it")
        dialog.focus_force()
        dialog.update()
        dialog.event_generate("<Escape>")
        dialog.update()
        assert not dialog.winfo_exists(), "Esc did not close the dialog"

    assert with_language_dialog(english, escape) is None
    assert not errors, errors
    assert not path.exists() and english.dirty

    reported = []

    def failed(dialog):
        dialog.choice.set("it")
        dialog.report = reported.append
        with patch("analisi.language_dialog.save_language", side_effect=PermissionError("read-only folder")):
            dialog.ok()
        assert dialog.winfo_exists(), "a failed write must keep the dialog open"
        assert not dialog.saved
        tools.capture(dialog, "window-language-error.png")
        dialog.cancel()

    english.status.set("before")
    assert with_language_dialog(english, failed) is None
    assert not errors, errors
    assert len(reported) == 1 and "read-only folder" in reported[0], reported
    assert not path.exists() and english.status.get() != i18n.translate("en", "language.saved")

    def confirm(dialog):
        dialog.choice.set("it")
        dialog.update()
        tools.capture(dialog, "window-language-dialog.png")
        dialog.ok()

    assert with_language_dialog(english, confirm) == "it"
    assert not errors, errors
    assert json.loads(path.read_text(encoding="utf-8")) == {"language": "it"}
    assert english.root.winfo_exists() and english.dirty, "confirming must not close or save"
    assert menu_labels(english) == MENUS_EN, "the running window keeps its language"
    assert english.status.get() == i18n.translate("en", "language.saved")
    english.dirty = False

    # 2. The next start with the same configuration is in Italian, menus and shortcuts unchanged.
    italian = start(i18n.load_language(path))
    front(italian)
    assert i18n.active_language() == "it"
    assert menu_labels(italian) == MENUS_IT, menu_labels(italian)
    entries_it, entries_en = menu_entries(italian), menu_entries(english)
    assert [len(menu) for menu in entries_it] == [len(menu) for menu in entries_en]
    assert ([[shortcut for _, shortcut in menu] for menu in entries_it]
            == [[shortcut for _, shortcut in menu] for menu in entries_en])
    edit_it = dict(entries_it[1])
    assert edit_it["Lingua…"] == "" and edit_it["Incolla speciale…"] == "Ctrl+Shift+V", edit_it
    for menu in entries_it:
        labels = [label for label, _ in menu]
        assert len(labels) == len(set(labels)), labels
    for sequence in SHORTCUTS:
        assert italian.root.bind(sequence) and english.root.bind(sequence), sequence
    setup = find(italian.page, TableSetup)
    assert [setup.types.get(index).strip() for index in range(setup.types.size())][:3] == [
        "XY", "Colonne", "Raggruppata"]
    assert setup.heading.cget("text") == "Tabelle XY"
    tools.capture(italian.root, "window-language-start-it.png")

    # 3. New XY table through the dialog, then import the accented CSV.
    def new_xy(dialog):
        dialog.setup.types.selection_clear(0, "end")
        dialog.setup.types.selection_set(0)
        dialog.setup.mode.set(False)
        dialog.setup.refresh()
        assert dialog.title() == "Nuova tabella e grafico", dialog.title()
        assert dialog.setup.option_label.cget("text") == "Opzioni"
        tools.capture(dialog, "window-language-new-table-it.png")

    tools.drive_dialog(NewTableDialog, new_xy)
    italian.new_table()
    assert not errors, errors
    assert italian.tables["XY"].table_format == "xy", italian.tables["XY"].table_format
    italian.root.update()
    assert italian.ribbon.winfo_manager() == "pack"
    assert ribbon_titles(italian)[:4] == ["File", "Foglio", "Annulla", "Appunti"], ribbon_titles(italian)
    italian.root.update_idletasks()
    for bar in (italian.ribbon,):
        assert bar.winfo_reqwidth() <= 1024, ("ribbon wider than 1024 px", bar.winfo_reqwidth())
    assert italian.current_grid.canvas.bind("<Control-Shift-V>")

    source = directory / "Intensità città.csv"
    shutil.copyfile(FIXTURES / "xy.csv", source)
    title = source.stem
    tools.drive_dialog(tools.TextImportDialog, lambda dialog: None)
    with patch.object(tools.filedialog, "askopenfilename", return_value=str(source)):
        italian.open_dialog(import_data=True)
    assert not errors, errors
    dataset = italian.tables[title]
    assert list(dataset.raw.columns) == ["X", "Intensità", "Serie B"], list(dataset.raw.columns)
    expected = pd.read_csv(FIXTURES / "xy.csv", encoding="utf-8")
    assert np.allclose(dataset.raw.astype(float).to_numpy(), expected.to_numpy(dtype=float), equal_nan=True)

    # Copy a block and paste it below: the numbers come back unchanged.
    italian.show("data", title)
    grid = italian.current_grid
    grid.select_block(0, 1, 3, 2)
    italian.copy_selection()
    grid.select((4, 1))
    italian.paste_selection()
    wait(italian)
    block = dataset.raw.iloc[:, 1:3].astype(float).to_numpy()
    assert np.allclose(block[4:8], block[0:4], equal_nan=True), block

    # Exclusion, calculated column, linear regression, layout.
    italian.show("data", title)
    italian.current_grid.select((2, 1))
    italian.toggle_exclusion()
    with patch.object(simpledialog, "askstring", side_effect=["Somma", '=COL("Intensità") + COL("Serie B")']):
        italian.add_formula()
    assert not errors, errors
    assert dataset.formulas == {"Somma": '=COL("Intensità") + COL("Serie B")'}, dataset.formulas
    assert dataset.excluded == {(2, 1)}, dataset.excluded

    def regression(dialog):
        tools.pick_method(dialog, "Linear regression")
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Serie B")

    tools.drive_dialog(tools.AnalysisDialog, regression)
    italian.choose_analysis()
    wait(italian)
    run = next(index for index, item in enumerate(italian.runs) if item.method == "Linear regression")
    assert italian.runs[run].result is not None

    def layout(dialog):
        dialog.name.set("Figura {A} – città")
        dialog.list.selection_set(0)
        dialog.add_selected()
        assert dialog.paper.get() == "Automatico", dialog.paper.get()

    tools.drive_dialog(tools.LayoutDialog, layout)
    italian.new_layout()
    assert not errors, errors
    assert [item.name for item in italian.layouts] == ["Figura {A} – città"]

    italian.show("data", title)
    italian.current_grid.select((2, 1))
    italian.root.update()
    tools.capture(italian.root, "window-language-it.png")

    # 4. A modified sheet and a project with several tabs: prompts and navigation in Italian.
    assert italian.dirty
    first = italian.active_project
    italian.refresh_project_tabs()
    assert italian.project_tabs.notebook.tab(first, "text").endswith(" *")
    with patch.object(tools.messagebox, "askyesnocancel", return_value=None) as ask:
        assert italian.confirm_saved() is False
    assert ask.call_args.args[0] == "Dati non salvati", ask.call_args.args
    assert ask.call_args.args[1].startswith("Salvare le modifiche a "), ask.call_args.args
    italian.new_project()
    second = italian.active_project
    italian.create_worksheet(TEMPLATES[1], True)
    assert len(italian.project_tabs.keys()) == 2
    sections = section_texts(italian)
    assert {"Famiglia", "Dati + Risultati", "Info", "Grafici", "Layout"} <= set(sections), sections
    italian.step_project(-1)
    assert italian.active_project == first and title in italian.tables
    italian.step_project(1)
    assert italian.active_project == second
    italian.step_project(-1)
    assert italian.status.get() != ""

    # Export through the combined Italian menu/dialog, with the sheet identities still canonical.
    from .pdf_bundle_dialog import PdfBundleDialog
    import pypdfium2 as pdfium

    bundle = directory / "italiano.pdf"

    def export_italian():
        dialog = find(italian.root, PdfBundleDialog)
        try:
            assert dialog is not None, "Italian PDF dialog did not open"
            assert dialog.title() == "Esporta più fogli in PDF"
            assert dialog.up.cget("text") == "Sposta su"
            dialog.listbox.selection_set(0, "end")
            dialog.width.set("76,2")
            dialog.update()
            tools.capture(dialog, "window-pdf-bundle-it.png")
            dialog.ok()
            assert not dialog.winfo_exists(), "Italian PDF export choices were rejected"
        except Exception as error:
            errors.append(f"Italian PDF dialog: {error!r}")
        finally:
            if dialog is not None and dialog.winfo_exists():
                dialog.cancel()

    italian.root.after(200, export_italian)
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(bundle)):
        italian.export_pdf_bundle()
    assert not errors, errors
    with pdfium.PdfDocument(bundle) as document:
        count = len(document)
        assert count >= 1
    pages = i18n.tr("pdf.one_page") if count == 1 else i18n.tr("pdf.many_pages", count=count)
    assert italian.status.get() == i18n.tr("pdf.exported", pages=pages, name=bundle.name)

    # 5. Save .alab: the status is translated, the archive holds no translated text.
    alab = directory / PROJECT
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(alab)):
        assert italian.save(as_new=True)
    assert italian.status.get() == "Salvato Misurazioni {A} – città.alab.", italian.status.get()
    assert not italian.dirty
    english_values = set(i18n.CATALOGS["en"].values())
    italian_only = {text for key, text in i18n.CATALOGS["it"].items()
                    if text not in english_values and len(text) >= 6 and not i18n.placeholders(text)}
    raw = alab.read_bytes()
    if raw[:2] == b"PK":
        with ZipFile(alab) as archive:
            content = "\n".join(archive.read(name).decode("utf-8", "ignore") for name in archive.namelist())
    else:
        content = json.dumps(json.loads(raw.decode("utf-8")), ensure_ascii=False)
    leaked = sorted(text for text in italian_only if text in content)
    assert not leaked, leaked

    # 6. Reopen with English: data, formulas, exclusions, recipes and layout references are identical.
    reopened = start("en")
    front(reopened)
    assert menu_labels(reopened) == MENUS_EN
    reopened.open_document(alab)
    wait(reopened)
    assert reopened.status.get() == "Opened Misurazioni {A} – città.alab.", reopened.status.get()
    assert set(reopened.tables) == set(italian.tables), (set(reopened.tables), set(italian.tables))
    for name, saved in italian.tables.items():
        loaded = reopened.tables[name]
        pd.testing.assert_frame_equal(loaded.raw, saved.raw)
        assert loaded.formulas == saved.formulas, name
        assert loaded.excluded == saved.excluded, name
        assert loaded.analyses == saved.analyses, name
        assert loaded.table_format == saved.table_format, name
    assert ([(item.name, item.columns, list(item.panels)) for item in reopened.layouts]
            == [(item.name, item.columns, list(item.panels)) for item in italian.layouts])
    for sequence in SHORTCUTS:
        assert reopened.root.bind(sequence), sequence
    reopened.show("data", title)
    reopened.current_grid.select((2, 1))
    reopened.root.update()
    tools.capture(reopened.root, "window-language-en.png")
    assert not errors, errors
