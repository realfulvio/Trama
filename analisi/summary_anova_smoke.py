"""Real-widget acceptance of summary ANOVA and its worksheet lifecycle."""
import json
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .presentation import graph_series
from .summary_anova import GAMES, JOINT, METHOD, TAMHANE


def check_summary_anova(root, app, directory, tools):
    out = directory/'summary-anova'; out.mkdir(exist_ok=True)
    language = i18n.active_language()
    wait = tools.wait_for_calculation

    def capture(window,name):
        tools.capture(window,name)
        source = directory/name
        if source.exists(): source.replace(out/name)

    def setup(dialog):
        tools.pick_method(dialog,METHOD)
        for name,value in {"Input":"Groups in rows","Group":"Group","Mean":"Mean",
                           "Dispersion":"SD","Sample size":"N","Post-hoc":"Tukey"}.items():
            dialog.controls[name][1].set(value)
        dialog.controls['Confidence level (%)'][1].set('100')
        with patch.object(tools.messagebox,'showerror') as error:
            assert dialog.validate() is False
            assert error.called
        dialog.controls['Confidence level (%)'][1].set('95')
        dialog.fields.select(0); dialog.update()
        assert dialog.winfo_rooty()+dialog.winfo_height() <= root.winfo_screenheight()
        capture(dialog,'dialog-summary-anova-'+i18n.active_language()+'.png')

    try:
        data = pd.DataFrame({'Group':['A','B','C'],'Mean':[2.,4.,6.],'SD':[1.,1.,1.],'N':[3,3,3]})
        path = out/'input.alab'; save_project(path,{'Summary':Dataset(data)})
        i18n.set_language('en'); app.import_file(path); app.show('data','Summary')
        tools.drive_dialog(tools.AnalysisDialog,setup); app.choose_analysis(only=METHOD); wait()
        index = len(app.runs)-1
        assert np.isclose(app.runs[index].result.tables['ANOVA'].iloc[0]['F'],12)
        app.show('graph',index);root.update();capture(root,'graph-summary-anova.png')
        for suffix in ('png','svg','pdf'): app.runs[index].result.figure.savefig(out/('summary-anova.'+suffix))
        app.show('result',index)
        with patch.object(tools.filedialog,'asksaveasfilename',return_value=str(out/'anova.csv')): app.export()
        i18n.set_language('it');tools.drive_dialog(tools.AnalysisDialog,setup);app.edit_analysis();wait()
        assert app.runs[index].options['Input']=='Groups in rows'
        app.show('data','Summary');app.current_grid.active_cell=(1,2);app.toggle_exclusion();wait()
        assert len(app.runs[index].result.tables['Summaries used'])==2
        assert app.runs[index].result.tables['Omitted groups'].iloc[0]['Source row']==2
        app.apply_worksheet_history();wait()
        app.edit_cell(0,1,'3');wait()
        assert not np.isclose(app.runs[index].result.tables['ANOVA'].iloc[0]['F'],12)
        roundtrip = out/'roundtrip.alab';app.path=roundtrip;assert app.save()
        i18n.set_language('en');app.import_file(roundtrip);app.show('graph',0)
        if app.runs[0].result is None:app.recalculate(0)
        wait();assert len(app.runs[0].result.tables['Summaries used'])==3
        app.show('result',0);app.result_tabs.select(1)
        count=len(app.tables);app.use_result_as_data();root.update();assert len(app.tables)==count+1

        wide=pd.DataFrame({f'{name} [{role}]':[value] for name,mean in (('A',2.),('B',4.),('C',6.))
                           for role,value in (('Mean',mean),('SEM',1/np.sqrt(3)),('N',3))})
        path=out/'wide.alab';save_project(path,{'Wide':Dataset(wide,table_format='grouped')})
        app.import_file(path);app.show('data','Wide')
        def wide_setup(dialog):
            tools.pick_method(dialog,METHOD)
            dialog.controls['Input'][1].set('Summary subcolumns')
            dialog.controls['Dispersion type'][1].set('SEM')
            tools.select_columns(dialog,'Variables',set(wide))
            dialog.controls['Summary row'][1].set('2')
            with patch.object(tools.messagebox,'showerror'): assert dialog.validate() is False
            dialog.controls['Summary row'][1].set('1')
            dialog.fields.select(0);dialog.update();capture(dialog,'dialog-summary-anova-wide.png')
        tools.drive_dialog(tools.AnalysisDialog,wide_setup);app.choose_analysis(only=METHOD);wait()
        assert np.isclose(app.runs[0].result.tables['ANOVA'].iloc[0]['F'],12)
        assert not tools.errors,tools.errors
        _check_unequal(root, app, out, tools, wait, capture)
        (out/'checks.json').write_text(json.dumps({'status':'PASS','screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
            'checks':['EN/IT controls','level and row validation','long and subcolumn inputs','edit/exclusion',
                      'roundtrip graph first','result as data','CSV/PNG/SVG/PDF','Welch and Brown–Forsythe',
                      'incompatible post-hoc','pointwise error bars','Inspector','legacy ordinary recipe']},indent=2))
    finally:i18n.set_language(language)


def _buttons(dialog):
    found = []
    def walk(widget):
        for child in widget.winfo_children():
            if "text" in child.keys() and child.cget("text") in {"Run Analysis", "Cancel", "Esegui analisi", "Annulla"}:
                found.append(child)
            walk(child)
    walk(dialog)
    return found


def _on_screen(dialog):
    dialog.update()
    assert dialog.winfo_rooty() + dialog.winfo_height() <= dialog.winfo_screenheight()
    buttons = _buttons(dialog)
    assert len(buttons) >= 2, [button.cget("text") for button in buttons]
    for button in buttons:
        assert button.winfo_viewable(), button.cget("text")
        assert button.winfo_rooty() >= 0
        assert button.winfo_rooty() + button.winfo_height() <= dialog.winfo_screenheight()
    return [(button.cget("text"), button.winfo_width(), button.winfo_height()) for button in buttons]


def _check_unequal(root, app, out, tools, wait, capture):
    """Welch, joint Brown–Forsythe, pointwise intervals and the unchanged ordinary recipe."""
    welch_f, brown_f = 16.947173633641757, 10.16611295681063
    data = pd.DataFrame({"Group": list("ABC"), "Mean": [10., 15., 18.], "SD": [2., 5., 3.], "N": [8, 12, 6]})
    path = out / "welch-input.alab"
    save_project(path, {"Welch": Dataset(data)})
    i18n.set_language("en")
    app.import_file(path)
    app.show("data", "Welch")

    def setup(dialog):
        tools.pick_method(dialog, METHOD)
        for name, value in {"Input": "Groups in rows", "Group": "Group", "Mean": "Mean", "Dispersion": "SD",
                            "Sample size": "N", "Method": "Ordinary", "Post-hoc": GAMES}.items():
            dialog.controls[name][1].set(value)
        with patch.object(tools.messagebox, "showerror") as error:
            assert dialog.validate() is False
            assert "Post-hoc" in error.call_args.args[1]
        assert dialog.controls["Group"][1].get() == "Group"
        assert dialog.controls["Post-hoc"][1].get() == GAMES
        dialog.controls["Method"][1].set("Welch")
        dialog.controls["Post-hoc"][1].set("Tukey")
        with patch.object(tools.messagebox, "showerror") as error:
            assert dialog.validate() is False
            assert "Post-hoc" in error.call_args.args[1]
            assert "Tukey" in error.call_args.args[1]
        assert dialog.controls["Mean"][1].get() == "Mean"
        assert dialog.focus_get() is dialog.field_rows["Post-hoc"][1]
        dialog.controls["Post-hoc"][1].set(GAMES)
        dialog.controls["Confidence level (%)"][1].set("95")
        dialog.fields.select(0)
        dialog.update()
        sizes = _on_screen(dialog)
        (out / "controls-en.json").write_text(json.dumps({"screen": [root.winfo_screenwidth(), root.winfo_screenheight()],
                                                          "buttons": sizes}, indent=2))
        capture(dialog, "dialog-summary-anova-welch-en.png")

    tools.drive_dialog(tools.AnalysisDialog, setup)
    app.choose_analysis(only=METHOD)
    wait()
    index = len(app.runs) - 1
    anova = app.runs[index].result.tables["ANOVA"]
    assert anova["Term"].tolist() == ["Welch"]
    assert "SS" not in anova
    assert np.isclose(anova.iloc[0]["F"], welch_f)
    used = app.runs[index].result.tables["Summaries used"]
    assert "Mean SE" in used and "Pooled mean CI lower" not in used
    pairs = app.runs[index].result.tables["Multiple comparisons"]
    assert pairs["Method"].tolist() == [GAMES, GAMES, GAMES]
    axes = app.runs[index].result.figure.axes[0]
    segments = axes.containers[0].lines[2][0].get_segments()
    np.testing.assert_allclose([segment[:, 1] for segment in segments],
                               np.column_stack((used["Mean CI lower"], used["Mean CI upper"])))
    assert "pointwise" in axes.get_legend().get_texts()[0].get_text().lower()
    app.show("graph", index)
    root.update()
    capture(root, "graph-summary-anova-welch.png")

    def joint(dialog):
        assert dialog.controls["Method"][1].get() == "Welch"
        assert dialog.controls["Mean"][1].get() == "Mean"
        dialog.controls["Method"][1].set(JOINT)
        dialog.controls["Post-hoc"][1].set(TAMHANE)
        dialog.controls["Confidence level (%)"][1].set("90,5")
        _on_screen(dialog)
        capture(dialog, "dialog-summary-anova-welch-it.png")

    i18n.set_language("it")
    tools.drive_dialog(tools.AnalysisDialog, joint)
    app.edit_analysis()
    wait()
    edited = app.runs[index]
    assert edited.options["Method"] == JOINT and edited.options["Post-hoc"] == TAMHANE
    assert edited.options["Confidence level (%)"] == 90.5
    assert edited.result.tables["ANOVA"]["Term"].tolist() == ["Welch", "Brown–Forsythe"]
    assert np.isclose(edited.result.tables["ANOVA"].iloc[0]["F"], welch_f)
    assert np.isclose(edited.result.tables["ANOVA"].iloc[1]["F"], brown_f)
    assert "CI lower" in edited.result.tables["Multiple comparisons"]
    saved_f = float(edited.result.tables["ANOVA"].iloc[0]["F"])
    roundtrip = out / "welch-roundtrip.alab"
    app.path = roundtrip
    assert app.save()

    app.show("data", "Welch")
    app.current_grid.active_cell = (1, 2)
    app.toggle_exclusion()
    wait()
    assert len(app.runs[index].result.tables["Summaries used"]) == 2
    assert app.runs[index].result.tables["Omitted groups"].iloc[0]["Source row"] == 2
    app.apply_worksheet_history()
    wait()
    assert len(app.runs[index].result.tables["Summaries used"]) == 3
    assert np.isclose(app.runs[index].result.tables["ANOVA"].iloc[0]["F"], saved_f)
    app.edit_cell(0, 1, "11")
    wait()
    assert not np.isclose(app.runs[index].result.tables["ANOVA"].iloc[0]["F"], saved_f)
    app.apply_worksheet_history()
    wait()

    i18n.set_language("en")
    app.import_file(roundtrip)
    app.show("graph", 0)
    if app.runs[0].result is None:
        app.recalculate(0)
    wait()
    reopened = app.runs[0]
    assert reopened.options["Method"] == JOINT and reopened.options["Post-hoc"] == TAMHANE
    assert np.isclose(reopened.result.tables["ANOVA"].iloc[0]["F"], welch_f)
    assert np.isclose(reopened.result.tables["ANOVA"].iloc[1]["F"], brown_f)
    app.show("result", 0)
    app.result_tabs.select(1)
    before = len(app.tables)
    app.use_result_as_data()
    root.update()
    assert len(app.tables) == before + 1

    app.show("graph", 0)
    root.update()
    axes = app.runs[0].result.figure.axes[0]
    options_before = dict(app.runs[0].options)
    original_title = axes.get_title()
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector is not None
    inspector.vars["title"].set("Not applied")
    inspector._now("title")
    assert axes.get_title() == "Not applied"
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None
    assert axes.get_title() == original_title
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    key = next(item.key for item in graph_series(axes) if item.kind == "errorbar")
    assert inspector.select_group(key)
    inspector.vars["element:color"].set("#d62728")
    inspector._now("element:color")
    inspector.vars["title"].set("Welch means")
    inspector._now("title")
    assert inspector.apply() is True
    assert axes.get_title() == "Welch means"
    assert app.runs[0].options == options_before
    inspector.cancel_button.invoke()
    root.update()
    assert axes.get_title() == "Welch means"

    def format_graph(dialog):
        dialog.inputs["title"].set("Welch means")

    tools.drive_dialog(tools.GraphFormatDialog, format_graph)
    app.format_graph()
    assert axes.get_title() == "Welch means"
    capture(root, "graph-summary-anova-welch-format.png")
    app.show("result", 0)
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(out / "welch-anova.csv")):
        app.export()
    exported = (out / "welch-anova.csv").read_text(encoding="utf-8")
    assert "Welch" in exported and "Brown" in exported
    app.show("graph", 0)
    for suffix, marker in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"welch-means.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        payload = target.read_bytes()
        assert payload.startswith(marker) or marker in payload[:300], suffix
    assert "pointwise" in (out / "welch-means.svg").read_text(encoding="utf-8").lower()
    assert (out / "welch-means.pdf").stat().st_size > 2000

    wide = pd.DataFrame({f"{name} [{role}]": [value] for name, mean, sd, size in (
        ("A", 10., 2., 8), ("B", 15., 5., 12), ("C", 18., 3., 6)) for role, value in (
            ("Mean", mean), ("SD", sd), ("N", size))})
    wide_path = out / "welch-wide.alab"
    save_project(wide_path, {"Wide": Dataset(wide, table_format="grouped")})
    app.import_file(wide_path)
    app.show("data", "Wide")

    def wide_setup(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["Input"][1].set("Summary subcolumns")
        dialog.controls["Method"][1].set("Welch")
        dialog.controls["Dispersion type"][1].set("SD")
        dialog.controls["Post-hoc"][1].set("None")
        tools.select_columns(dialog, "Variables", set(wide))
        dialog.controls["Summary row"][1].set("1")
        _on_screen(dialog)

    tools.drive_dialog(tools.AnalysisDialog, wide_setup)
    app.choose_analysis(only=METHOD)
    wait()
    assert np.isclose(app.runs[0].result.tables["ANOVA"].iloc[0]["F"], welch_f)

    legacy = pd.DataFrame({"Group": list("ABC"), "Mean": [2., 4., 6.], "SD": [1., 1., 1.], "N": [3, 3, 3]})
    legacy_options = {"Input": "Groups in rows", "Group": "Group", "Mean": "Mean", "Dispersion": "SD",
                      "Sample size": "N", "Dispersion type": "SD", "Post-hoc": "Tukey", "Confidence level (%)": 95.}
    legacy_path = out / "legacy-ordinary.alab"
    save_project(legacy_path, {"Legacy": Dataset(legacy, analyses=[(METHOD, legacy_options)])})
    app.import_file(legacy_path)
    app.show("graph", 0)
    if app.runs[0].result is None:
        app.recalculate(0)
    wait()
    legacy_run = app.runs[0]
    assert "Method" not in legacy_run.options
    assert np.isclose(legacy_run.result.tables["ANOVA"].iloc[0]["F"], 12)
    assert "SS" in legacy_run.result.tables["ANOVA"]
    assert "Pooled mean CI lower" in legacy_run.result.tables["Summaries used"]
    assert not tools.errors, tools.errors
