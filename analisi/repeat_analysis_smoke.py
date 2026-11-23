"""Real desktop acceptance of Analysis → Repeat analysis on other sheets… in the classic Tk window.

Alone: ``TRAMASTAT_SMOKE_ONLY=repeat-analysis python tramastat.py --smoke DIR``. It drives the mapped widgets of
the application (the Analyze menu, the navigator context menu, the three steps of the assistant, the worker and
its Cancel, Change input result…, saving and reopening) in English and Italian on the screen of the running
process, on a synthetic project written into DIR first. It does not simulate manual pointer use and does not
measure the system DPI. Screenshots ``window-repeat-*-<lang>.png``; the project is saved as
``repeat-analysis/<lang>/repeat.alab``.
"""
import time
import tkinter as tk

import pandas as pd

from . import i18n
from .analysis_chain import ResultSource
from .analysis_source_dialog import AnalysisSourceDialog
from .data import Dataset, project_bytes, save_project
from .graph_language_smoke import drive_mapped_dialog
from .repeat_analysis_dialog import RepeatDialog
from .repeat_analysis_text import t

PARENT_ID = "664dd2e3-7bc3-4648-86c7-29493b5e3d62"
CHILD_ID = "a875096c-bd16-4f69-be97-937175df241d"
MAPPINGS = {"Lot B": {"X": "Tempo", "Y": "Segnale"}, "Lot C": {"X": "Concentrazione", "Y": "Risposta"},
            "Short": {"X": "A", "Y": "B"}}
COMMAND = "Analyze", "Repeat analysis on other sheets…"


def fixture_tables():
    """The project of the acceptance packet, plus a sheet too short for a regression."""
    original = Dataset(pd.DataFrame({"X": [0., 1., 4.], "Y": [1., 2., 5.]}), analyses=[
        ("Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"}),
        ("Linear regression", {"X": "X", "Y": "Y"}),
    ], analysis_ids={0: PARENT_ID, 1: CHILD_ID}, analysis_sources={1: ResultSource(PARENT_ID, "Transformed")})
    return {"Original": original,
            "Lot B": Dataset(pd.DataFrame({"Tempo": [0., 1., 4.], "Segnale": [1., 3., 9.]})),
            "Lot C": Dataset(pd.DataFrame({"Concentrazione": [0., 1., 4.], "Risposta": [4., 9., 24.]})),
            "Short": Dataset(pd.DataFrame({"A": [1., 2.], "B": [3., 5.]}))}


def check_repeat_analysis(root, app, directory, tools):
    """``tools`` carries App, capture and the smoke's errors list."""
    out = directory / "repeat-analysis"
    out.mkdir(parents=True, exist_ok=True)
    original_language = i18n.active_language()
    windows = []
    try:
        for code in ("en", "it"):
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
            window.geometry(f"{min(screen[0], 1560)}x{min(screen[1], 930)}+0+0")
            window.update()
            _scenario(root, instance, out / code, tools, code)
    finally:
        for instance in windows:
            instance.worker.shutdown(wait=False)
            instance.root.destroy()
        i18n.set_language(original_language)
        root.deiconify()
        root.update()


def _scenario(root, app, out, tools, code):
    out.mkdir(parents=True, exist_ok=True)
    errors = tools.errors

    def finish():
        deadline = time.monotonic() + 40
        while app.pending is not None:
            assert time.monotonic() < deadline, "The worker did not finish"
            root.update()
            time.sleep(.02)
        for _ in range(5):  # A reopened assistant arrives through an idle callback.
            root.update()

    def run_index(title, slot):
        return next(i for i, run in enumerate(app.runs) if run.reference == (title, slot))

    def slope(run):
        assert run.result is not None and run.calculation_error is None, (run.title, run.calculation_error)
        return float(run.result.tables["Regression"].loc["Slope", "Value"])

    def inside(widget):
        root.update_idletasks()
        assert widget.winfo_viewable(), widget
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        assert 0 <= x and x + widget.winfo_width() <= root.winfo_screenwidth(), widget
        assert 0 <= y and y + widget.winfo_height() <= root.winfo_screenheight(), widget

    def fill(dialog, targets, shots=False):
        """Recipe with its downstream step, sheets and columns chosen by hand, preview."""
        assert str(dialog.follow_button.cget("state")) != "disabled" and dialog.follow_var.get()
        summary = dialog.summary.get("1.0", "end")
        assert i18n.ui("Linear regression") in summary or "Linear regression" in summary, summary
        for widget in (dialog.next_button, dialog.cancel_button, dialog.summary):
            inside(widget)
        if shots:
            tools.capture(dialog, f"window-repeat-recipe-{code}.png")
        dialog.next_button.invoke()
        assert dialog.page == 1
        assert "Original" in dialog.refused, dialog.refused
        dialog.toggle("Original")
        assert "Original" not in dialog.assistant.selected
        for title in targets:
            dialog.toggle(title, True)
            root.update()
            assert dialog.next_button.instate(["disabled"]), f"Next enabled before the columns of {title}"
            for column, chosen in MAPPINGS[title].items():
                dialog.boxes[column].set(chosen)
                dialog.boxes[column].event_generate("<<ComboboxSelected>>")
            if shots and title == "Lot B":  # A duplicate choice blocks Next and says why.
                dialog.boxes["Y"].set("Tempo")
                dialog.boxes["Y"].event_generate("<<ComboboxSelected>>")
                assert dialog.next_button.instate(["disabled"])
                assert "Tempo" in dialog.status_var.get(), dialog.status_var.get()
                tools.capture(dialog, f"window-repeat-duplicate-{code}.png")
                dialog.boxes["Y"].set("Segnale")
                dialog.boxes["Y"].event_generate("<<ComboboxSelected>>")
        root.update()
        assert dialog.next_button.instate(["!disabled"]), dialog.status_var.get()
        assert dialog.status_var.get() == t("ready"), dialog.status_var.get()
        for widget in (dialog.sheet_list, dialog.next_button, dialog.back_button, *dialog.boxes.values()):
            inside(widget)
        if shots:
            tools.capture(dialog, f"window-repeat-sheets-{code}.png")
        dialog.next_button.invoke()
        assert dialog.page == 2 and dialog.plan is not None
        root.update()
        inside(dialog.apply_button)
        if shots:
            tools.capture(dialog, f"window-repeat-preview-{code}.png")

    def repeat(targets, *, shots=False, during=None, reopened=None, via="menu"):
        seen = []

        def ready(dialog):
            seen.append(dialog)
            try:
                if len(seen) == 1:
                    fill(dialog, targets, shots)
                    dialog.apply_button.invoke()
                    return
                if reopened is not None:
                    reopened(dialog)
            except Exception as error:
                errors.append(f"RepeatDialog: {error!r}")
            if dialog.winfo_exists():
                dialog.cancel()

        app.open_sheet(("result", run_index("Original", 0)))
        finish()
        drive_mapped_dialog(root, RepeatDialog, ready, errors, timeout=30)
        if via == "menu":
            popup, index = app.menu_entries[COMMAND]
            assert popup.entrycget(index, "label") == t("command")
            popup.invoke(index)
        else:
            node = next(node for node, ref in app.nodes.items() if ref == ("result", run_index("Original", 0)))
            app.update_nav_menu(node)
            assert str(app.nav_menu.entrycget(7, "state")) == "normal"
            app.nav_menu.invoke(7)
        if reopened is not None:
            # The menu invocation returns after the original modal dialog closes. Only now wait for the next one.
            drive_mapped_dialog(root, RepeatDialog, ready, errors, timeout=30)
        if during is not None and app.pending is not None:
            during()
        finish()
        return seen

    # -- the project ----------------------------------------------------------------------------------
    path = out / "repeat-fixture.alab"
    save_project(path, fixture_tables())
    app.import_file(path)
    finish()
    for slot in (0, 1):
        app.open_sheet(("result", run_index("Original", slot)))
        finish()
    assert abs(slope(app.runs[run_index("Original", 1)]) - 1.) < 1e-12
    count = len(app.runs)
    source_bytes = project_bytes({"Original": app.tables["Original"]})

    # -- Cancel during the calculation ------------------------------------------------------------------
    before = project_bytes(app.tables)
    repeat(["Lot B", "Lot C"], during=app.cancel_calculation)
    assert project_bytes(app.tables) == before and len(app.runs) == count, "Cancel changed the project"
    assert app.status.get() == t("cancelled"), app.status.get()
    assert not errors, errors

    # -- a project changed during the calculation -----------------------------------------------------
    def change():
        app.tables["Lot C"].raw.iat[0, 1] = 4.5

    repeat(["Lot B", "Lot C"], during=change)
    assert errors == [t("changed")], errors
    errors.clear()
    assert len(app.runs) == count and not app.tables["Lot B"].analyses and not app.tables["Lot C"].analyses
    app.tables["Lot C"].raw.iat[0, 1] = 4.

    # -- a copy that cannot be calculated: the same assistant again ------------------------------------
    before = project_bytes(app.tables)
    notices = []

    def failed(dialog):
        notices.append(dialog.banner_var.get())
        assert dialog.page == 1 and "Short" in dialog.assistant.selected
        inside(dialog.banner)
        tools.capture(dialog, f"window-repeat-failed-{code}.png")

    seen = repeat(["Lot B", "Short"], reopened=failed, via="navigator")
    assert len(seen) == 2 and seen[0].assistant is seen[1].assistant, seen
    assert notices and "Short" in notices[0], notices
    assert project_bytes(app.tables) == before and len(app.runs) == count, "a failed copy changed the project"
    assert not errors, errors

    # -- the two copies -------------------------------------------------------------------------------
    repeat(["Lot B", "Lot C"], shots=True)
    assert not errors, errors
    assert len(app.runs) == count + 4, len(app.runs) - count
    assert app.dirty
    for title, expected in (("Lot B", 2.), ("Lot C", 5.)):
        parent = app.runs[run_index(title, 0)]
        child = app.runs[run_index(title, 1)]
        assert parent.method == "Transform" and child.method == "Linear regression"
        assert abs(slope(child) - expected) < 1e-8, (title, slope(child))
        assert child.source == ResultSource(parent.uid, "Transformed")
        assert parent.uid not in (PARENT_ID, CHILD_ID)
    assert project_bytes({"Original": app.tables["Original"]}) == source_bytes, "the source changed"
    assert app.status.get().startswith(t("done", analyses=4, sheets=2)), app.status.get()
    tools.capture(app.root, f"window-repeat-added-{code}.png")

    # Change input result… recognises the copies.
    app.open_sheet(("result", run_index("Lot B", 1)))
    finish()
    sources = []

    def change_input(dialog):
        sources.append(dialog)
        dialog.cancel()

    drive_mapped_dialog(root, AnalysisSourceDialog, change_input, errors, timeout=30)
    app.change_input_result()
    root.update()
    assert sources, "Change input result… did not open"
    # Editing an option of a copy leaves the source intact.
    method, options = app.tables["Lot B"].analyses[1]
    app.tables["Lot B"].analyses[1] = (method, {**options, "Confidence level": 0.9})
    assert app.tables["Original"].analyses[1][1].get("Confidence level") != 0.9
    app.tables["Lot B"].analyses[1] = (method, options)

    # -- save and reopen ------------------------------------------------------------------------------
    saved = out / "repeat.alab"
    app.sync_analysis_links(persist=True)
    save_project(saved, app.tables)
    app.dirty = False
    app.import_file(saved)
    finish()
    for title, expected in (("Original", 1.), ("Lot B", 2.), ("Lot C", 5.)):
        index = run_index(title, 1)
        app.open_sheet(("result", index))
        finish()
        assert abs(slope(app.runs[index]) - expected) < 1e-8, title
    assert not errors, errors
