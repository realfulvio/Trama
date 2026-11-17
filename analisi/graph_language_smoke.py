"""Desktop smoke check for Italian in Format Graph and the Inspector, kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_graph_language` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=graph-language python tramastat.py --smoke DIR``.

A synthetic XY project with two series and a right axis is formatted in Italian through the real controls
(the translated labels are picked, never the canonical values), saved, and reopened in English and in
Italian. The recipe and the graph styles must hold the same canonical values in every case, and the
exported SVG must carry the user's labels literally.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import time
import tkinter as tk
from tkinter import simpledialog, ttk
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

from matplotlib import rc_context
import numpy as np
import pandas as pd

from . import i18n, ui_theme
from .graph_dialog import GraphFormatDialog

PROJECT = "Formato {A} – città & $.alab"
TABLE = "Clima {B} – città"
TITLE = "Titolo {A} – città & $"
RIGHT_TITLE = "Pressione · città"
SCREEN = (1024, 768)


def drive_mapped_dialog(root, kind, ready, errors, *, timeout=8.):
    """Wait for visibility and, for simpledialog, its modal grab before operating the controls."""
    deadline=time.monotonic()+timeout
    def find(parent):
        for child in parent.winfo_children():
            if isinstance(child,kind):return child
            found=find(child)
            if found is not None:return found
        return None
    def enter():
        dialog=find(root)
        if (dialog is None or not dialog.winfo_viewable()
                or isinstance(dialog, simpledialog.Dialog) and dialog.grab_current() is not dialog):
            if time.monotonic()<deadline:root.after(30,enter);return
            errors.append(f"{kind.__name__} did not finish initialization")
            if dialog is not None:dialog.cancel()
            return
        ready(dialog)
    root.after(30,enter)


def check_graph_language(root, app, directory, tools):
    """``tools`` carries App, AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    messagebox, filedialog, Dataset, save_project and the smoke's errors list."""
    config = directory / "graph-config"
    shutil.rmtree(config, ignore_errors=True)
    original_language = i18n.active_language()
    original_theme = ui_theme._state.get("theme", "standard")
    windows = []
    try:
        # Temporary preferences: nothing reads or writes the user's own configuration.
        with patch.dict(os.environ, {"APPDATA": str(config), "XDG_CONFIG_HOME": str(config)}):
            _check(root, app, directory, tools, windows)
    finally:
        for instance in windows:
            instance.worker.shutdown(wait=False)
            instance.root.destroy()
        i18n.set_language(original_language)
        ui_theme.configure(root, original_theme)
        root.deiconify()


def _check(root, app, directory, tools, windows):
    errors = tools.errors

    def start(language):
        """A new instance with the language read at startup, like main() does."""
        i18n.set_language(language)
        window = tk.Toplevel(root)
        instance = tools.App(window)
        instance.error = lambda error: errors.append(str(error))
        windows.append(instance)
        for other in windows:
            if other is not instance and other.root.winfo_exists():
                other.root.withdraw()
        root.withdraw()
        window.geometry(f"{SCREEN[0]}x{SCREEN[1]}+0+0")
        window.update()
        return instance

    def wait(instance):
        deadline = time.monotonic() + 30
        while instance.pending is not None:
            if time.monotonic() > deadline:
                raise TimeoutError("Analysis did not complete")
            root.update()
            time.sleep(.02)
        assert not errors, errors

    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)

    def open_format(instance, action, *, accept):
        def enter(dialog):
            try:
                action(dialog)
                if dialog.winfo_exists():
                    dialog.ok() if accept else dialog.cancel()
                if dialog.winfo_exists():
                    errors.append("Format Graph rejected the choices")
            except Exception as error:  # report after the modal loop, never leave the dialog open
                errors.append(f"Format Graph: {error!r}")
            if dialog.winfo_exists():
                dialog.cancel()

        before = len(errors)
        drive_mapped_dialog(root, GraphFormatDialog, enter, errors)
        instance.format_graph()
        assert errors[before:] == [], errors[before:]

    def pick(combobox, label):
        """Choose a displayed label exactly as a user does."""
        labels = list(combobox.cget("values"))
        assert label in labels, (label, labels)
        combobox.current(labels.index(label))
        combobox.event_generate("<<ComboboxSelected>>")

    def binding(dialog, widget):
        return dialog.choices[str(widget)]

    def scale_widget(dialog, dimension):
        return next(widget for widget in descendants(dialog) if isinstance(widget, ttk.Combobox)
                    and str(widget) in dialog.choices
                    and dialog.choices[str(widget)].variable is dialog.inputs[dimension + "scale"])

    def legend_widget(dialog):
        return next(widget for widget in descendants(dialog) if isinstance(widget, ttk.Combobox)
                    and str(widget) in dialog.choices
                    and dialog.choices[str(widget)].variable is dialog.appearance["legend"])

    def select_series(dialog, name):
        names = list(dialog.series_selector.cget("values"))
        dialog.series_selector.current(names.index(name))
        dialog._select_series()

    def fits(dialog):
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        assert width <= SCREEN[0] and height <= SCREEN[1], ("Format Graph larger than 1024×768", width, height)

    def inspector_fits(instance):
        inspector = instance.inspector
        instance.root.update()
        window_bottom = instance.root.winfo_rooty() + instance.root.winfo_height()
        for button in (inspector.apply_button, inspector.cancel_button):
            assert button.winfo_ismapped(), button.cget("text")
            assert button.winfo_rooty() + button.winfo_height() <= window_bottom + 1, button.cget("text")
            assert button.winfo_width() >= button.winfo_reqwidth(), button.cget("text")
        right = inspector.scroller.winfo_rootx() + inspector.scroller.winfo_width()
        for control in inspector._controls(inspector.body):
            if control.winfo_ismapped():
                assert control.winfo_rootx() + control.winfo_width() <= right + 1, str(control)

    # 1. A synthetic project: two XY series whose names are keywords of the controls.
    source = pd.DataFrame({"X": [1., 2, 3, 4, 5], "Default": [2., 3, 5, 8, 13], "Right": [900., 950, 1010, 1080, 1150]})
    seed = directory / "graph-language-seed.alab"
    tools.save_project(seed, {TABLE: tools.Dataset(source)})

    italian = start("it")
    italian.import_file(seed)

    def choose(dialog):
        tools.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("X")
        tools.select_columns(dialog, "Y columns", ["Default", "Right"])

    tools.drive_dialog(tools.AnalysisDialog, choose)
    italian.choose_analysis()
    wait(italian)
    italian.show("graph", 0)
    italian.root.update()
    assert italian.inspector_button.cget("text") == "Ispettore", italian.inspector_button.cget("text")

    # 2. Format Graph in Italian: left scale, legend, series side and draw style, through the labels.
    def format_italian(dialog):
        assert dialog.title() == "Formato grafico", dialog.title()
        tabs = [dialog.notebook.tab(tab, "text") for tab in dialog.notebook.tabs()]
        assert tabs == ["Aspetto", "Assi", "Serie", "Linee di riferimento"], tabs
        fits(dialog)
        dialog.inputs["title"].set(TITLE)
        legend = legend_widget(dialog)
        assert legend.get() == "Predefinito dell'analisi", legend.get()
        pick(legend, "in alto a sinistra")
        assert dialog.appearance["legend"].get() == "upper left"
        dialog.notebook.select(1)
        dialog.update()
        scale = scale_widget(dialog, "y")
        for widget in (scale, scale_widget(dialog, "x")):
            assert widget.winfo_width() >= widget.winfo_reqwidth(), "scale choices are squeezed"
        pick(scale, "Logaritmica")
        assert dialog.inputs["yscale"].get() == "log"
        right_scale = next(widget for widget in descendants(dialog) if isinstance(widget, ttk.Combobox)
                           and str(widget) in dialog.choices and dialog.choices[str(widget)].variable is dialog.right_scale)
        assert right_scale.cget("values") == ("Lineare", "Logaritmica"), right_scale.cget("values")
        assert dialog.right_scale.get() == "Linear"
        dialog.right_title.set(RIGHT_TITLE)
        tools.capture(dialog, "window-graph-format-axes-it.png")
        dialog.notebook.select(2)
        dialog.update()
        assert list(dialog.series_selector.cget("values")) == ["Default", "Right"], dialog.series_selector.cget("values")
        select_series(dialog, "Default")
        pick(dialog._draw_widget, "Linea e punti")
        assert dialog.draw_style.get() == "Line and points"
        dialog.series_fields["color"].set("#aa3377")
        select_series(dialog, "Right")
        assert binding(dialog, dialog._side_widget).labels == ("Sinistra", "Destra")
        pick(dialog._side_widget, "Destra")
        assert dialog.side.get() == "Right"
        tools.capture(dialog, "window-graph-format-series-it.png")

    open_format(italian, format_italian, accept=True)
    run = italian.runs[0]
    table = italian.tables[TABLE]
    assert run.options["Series side"] == {"Default": "Left", "Right": "Right"}, run.options["Series side"]
    assert run.options["Series style"] == {"Default": "Line and points", "Right": "Points"}, run.options["Series style"]
    assert run.options["Right scale"] == "Linear" and run.options["Right title"] == RIGHT_TITLE, run.options
    assert run.style["yscale"] == "log" and run.style["legend"] == "upper left", run.style
    assert run.style["title"] == TITLE, run.style["title"]
    assert run.style["series"] == {"xy:1:Default": {"color": "#aa3377"}}, run.style["series"]
    assert table.graph_styles[0] == run.style
    left = run.result.figure.axes[0]
    assert left.get_yscale() == "log" and left.get_title() == TITLE, (left.get_yscale(), left.get_title())

    alab = directory / PROJECT
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(alab)):
        assert italian.save(as_new=True)
    assert not italian.dirty

    # 3. Inspector in Italian: one change is cancelled, another is applied.
    italian.show("graph", 0)
    italian.toggle_inspector()
    inspector = italian.inspector
    assert inspector is not None, "Inspector did not open"
    assert not inspector.has_draft and not italian.dirty, "opening the Italian panel changed the project"
    assert (inspector.apply_button.cget("text"), inspector.cancel_button.cget("text")) == ("Applica", "Annulla")
    sections = [inspector.widgets[name].cget("text") for name in ("data", "axes", "page")]
    assert sections == ["Dati", "Assi", "Pagina"], sections
    inspector_fits(italian)
    legend = inspector.choices["legend"].combobox
    assert legend.get() == "in alto a sinistra", legend.get()
    pick(legend, "in basso a destra")
    assert inspector.draft["legend"] == "lower right", inspector.draft
    assert run.style["legend"] == "upper left"
    tools.capture(italian.root, "window-graph-inspector-it.png")
    inspector.cancel_button.invoke()
    italian.root.update()
    assert italian.inspector is None and run.style["legend"] == "upper left", run.style
    assert not italian.dirty, "a cancelled Inspector change made the project dirty"

    italian.toggle_inspector()
    inspector = italian.inspector
    inspector.select_group("xy:1:Right")
    pick(inspector.choices["legend"].combobox, "in alto al centro")
    inspector.vars["element:color"].set("#117733")
    inspector._now("element:color")
    assert inspector.apply(), inspector.status.cget("text")
    assert inspector.status.cget("text") == "Applicato."
    assert run.style["legend"] == "upper center", run.style
    assert run.style["series"]["xy:1:Right"] == {"color": "#117733"}, run.style["series"]
    assert italian.dirty
    inspector.cancel_button.invoke()
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(alab)):
        assert italian.save(as_new=True)
    assert not italian.dirty
    expected_options = deepcopy(run.options)
    expected_style = deepcopy(run.style)

    # The project file holds canonical values only: no stored string is an Italian choice or caption.
    raw = alab.read_bytes()
    if raw[:2] == b"PK":
        with ZipFile(alab) as archive:
            documents = [json.loads(archive.read(name)) for name in archive.namelist() if name.endswith(".json")]
    else:
        documents = [json.loads(raw.decode("utf-8"))]
    stored = set()

    def strings(value):
        if isinstance(value, str):
            stored.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                strings(key)
                strings(item)
        elif isinstance(value, list):
            for item in value:
                strings(item)

    for document in documents:
        strings(document)
    assert {"log", "upper center", "Right", "Line and points", "Linear"} <= stored, "canonical values are stored"
    english_texts = set(i18n.CATALOGS["en"].values())
    italian_only = {text for key, text in i18n.CATALOGS["it"].items()
                    if key.startswith("graph.") and text not in english_texts}
    leaked = sorted(stored & italian_only)
    assert not leaked, leaked

    def export(instance, name):
        svg, png = directory / f"{name}.svg", directory / f"{name}.png"
        instance.show("graph", 0)
        with rc_context({"svg.fonttype": "none"}), \
                patch.object(tools.filedialog, "asksaveasfilename", return_value=str(svg)):
            instance.export()
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(png)):
            instance.export()
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", png
        texts = {"".join(node.itertext()).strip() for node in ElementTree.parse(svg).iter()
                 if node.tag.endswith("text")}
        for label in (TITLE, RIGHT_TITLE, "Default", "Right"):
            assert label in texts, (label, sorted(texts))
        return texts

    italian_texts = export(italian, "graph-language-it")

    # 4. Reopen the same project in English and in Italian: identical canonical values, nothing dirty.
    def reopen(language):
        instance = start(language)
        instance.open_document(alab)
        wait(instance)
        instance.open_sheet(("graph", 0))
        wait(instance)
        loaded = instance.runs[0]
        assert loaded.options == expected_options, (language, loaded.options)
        assert loaded.style == expected_style, (language, loaded.style)
        assert instance.tables[TABLE].graph_styles[0] == expected_style
        assert instance.tables[TABLE].analyses == italian.tables[TABLE].analyses
        assert not instance.dirty
        return instance

    english = reopen("en")
    assert english.inspector_button.cget("text") == "Inspector"

    def format_english(dialog):
        assert dialog.title() == "Format Graph", dialog.title()
        fits(dialog)
        assert legend_widget(dialog).get() == "upper center", legend_widget(dialog).get()
        dialog.notebook.select(1)
        dialog.update()
        assert scale_widget(dialog, "y").get() == "Logarithmic"
        assert scale_widget(dialog, "y").cget("values")[:2] == ("Linear", "Logarithmic")
        tools.capture(dialog, "window-graph-format-axes-en.png")
        dialog.notebook.select(2)
        select_series(dialog, "Right")
        assert dialog._side_widget.get() == "Right" and dialog.side.get() == "Right"
        tools.capture(dialog, "window-graph-format-series-en.png")

    open_format(english, format_english, accept=False)
    english.toggle_inspector()
    assert english.inspector.apply_button.cget("text") == "Apply"
    assert english.inspector.choices["legend"].combobox.get() == "upper center"
    inspector_fits(english)
    tools.capture(english.root, "window-graph-inspector-en.png")
    english.inspector.cancel_button.invoke()
    assert not english.dirty, "English Format Graph or Inspector made the project dirty"
    english_texts = export(english, "graph-language-en")
    assert {TITLE, RIGHT_TITLE} <= english_texts & italian_texts

    again = reopen("it")

    def format_again(dialog):
        assert legend_widget(dialog).get() == "in alto al centro", legend_widget(dialog).get()
        assert scale_widget(dialog, "y").get() == "Logaritmica"

    open_format(again, format_again, accept=True)
    assert again.runs[0].style == expected_style, again.runs[0].style
    assert again.runs[0].options == expected_options
    assert not errors, errors
    np.testing.assert_allclose(again.tables[TABLE].raw["Right"].astype(float), source["Right"])
    return Path(alab)
