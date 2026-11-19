"""Smoke of the analysis templates (``qt-analysis-templates``).

Run inside ``python -m trama_qt --smoke FOLDER`` (after the project tabs) and on its own with
``python -m trama_qt --smoke FOLDER --only qt-analysis-templates``, which repeats it in English and Italian with the
light and the dark theme without reading or writing the user's preferences.

The scenario is the one of the package: a two-table project (formula ``Scaled = 2*Y+1``, Transform → Normalize →
Linear regression, a direct regression, a regression of the second table, a two-panel layout) is calculated from
its layout and saved as a template; the JSON holds no observation. The new data are opened as sheets of a second
project and mapped in the real assistant, with a duplicate assignment and an empty field first. The new project
gives slopes 6, 3 and 5, is saved, reopened from its layout and edited; a second application gets other
identities. Two damaged templates, six open projects, Cancel while building and an Info reference out of scope
are refused without touching the other tabs. Screenshots ``<lang>-templates-*.png`` and ``templates-<lang>.txt``
(times, tab states) go to the smoke folder.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time
from unittest import mock

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QDialog, QFileDialog

SENTINEL = "SOLO_ORIGINALE_Ω"
IDS = [f"00000000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3, 4, 6)]
MAPPING = {"Analisi α": ["Campioni nuovi", {"X": "Dose", "Y": "Segnale (mV)", "Badge": "Campione"}],
           "Controllo": ["Controlli nuovi", {"Time": "t (s)", "Signal": "Misura"}]}


def write_fixtures(folder):
    """The package fixtures, written by code so the smoke needs no test folder (portable build)."""
    from analisi.analysis_chain import ResultSource
    from analisi.data import Dataset, save_project
    from analisi.presentation import Layout
    folder.mkdir(parents=True, exist_ok=True)
    first = Dataset(pd.DataFrame({"X": [1, 2, 3, 4], "Y": [3, 5, 7, 9], "Badge": pd.Series([SENTINEL] * 4,
                                                                                         dtype="string")}),
                    formulas={"Scaled": "=2*Y+1"},
                    analyses=[("Transform", {"Variables": ["X", "Scaled"], "Operation": "Absolute value"}),
                              ("Normalize", {"Variables": ["X", "Scaled"], "Method": "Subtract first value"}),
                              ("Linear regression", {"X": "X", "Y": "Scaled"}),
                              ("Linear regression", {"X": "X", "Y": "Y"})],
                    excluded={(2, 2)}, graph_styles={2: {"title": "Controllo $ α", "ylabel": "Risposta"}},
                    analysis_ids=dict(enumerate(IDS[:4])),
                    analysis_sources={1: ResultSource(IDS[0], "Transformed"), 2: ResultSource(IDS[1], "Normalized")},
                    analysis_labels={2: "Curva corretta $"})
    second = Dataset(pd.DataFrame({"Time": [1, 2, 3, 4], "Signal": [2, 3, 4, 5]}),
                     analyses=[("Linear regression", {"X": "Time", "Y": "Signal"})], analysis_ids={0: IDS[4]})
    original = folder / "progetto-originale.alab"
    save_project(original, {"Analisi α": first, "Controllo": second},
                 layouts=[Layout("Report 2 pannelli", 2, [("Analisi α", 2), ("Controllo", 0)], "Automatic",
                                 "#f4f6f9")])
    (folder / "Campioni nuovi.csv").write_text("Campione,Segnale (mV),Dose,Extra\n0003,5,1,A\n0004,8,2,B\n"
                                               "0005,11,3,C\n0006,14,4,D\n", encoding="utf-8")
    (folder / "Controlli nuovi.csv").write_text("t (s),Misura\n1,6\n2,11\n3,16\n4,21\n", encoding="utf-8")
    (folder / "mappatura.json").write_text(json.dumps(MAPPING, ensure_ascii=False, indent=2), encoding="utf-8")
    return original


def settle(smoke, timeout=120):
    """Until no job runs and none is about to start: a finished read opens the assistant on the next event
    turn, and a finished build starts the calculation, so one quiet turn is not enough."""
    end, quiet = time.monotonic() + timeout, 0
    while time.monotonic() < end:
        smoke.app.processEvents()
        quiet = quiet + 1 if smoke.window.job is None else 0
        if quiet >= 4:
            return
        time.sleep(0.02)
    raise RuntimeError("calculation still running")


def slopes(project):
    return [round(float(run.result.tables["Regression"].loc["Slope", "Value"]), 9)
            for run in project.runs if run.method == "Linear regression" and run.result is not None]


@contextmanager
def driving(smoke, handlers):
    """``QDialog.exec`` of the template dialogs runs the next handler; other dialogs are a problem."""
    from . import templates
    original = QDialog.exec
    queue = list(handlers)

    def exec_(dialog):
        if not isinstance(dialog, (templates.SaveTemplateDialog, templates.TemplateWizard)) or not queue:
            smoke.problem(f"templates: unexpected dialog {type(dialog).__name__}")
            return QDialog.DialogCode.Rejected
        dialog.show()
        smoke.app.processEvents()
        accepted = queue.pop(0)(dialog)
        if accepted:
            return QDialog.DialogCode.Accepted
        dialog.reject()
        return QDialog.DialogCode.Rejected

    QDialog.exec = exec_
    try:
        yield queue
    finally:
        QDialog.exec = original
    if queue:
        smoke.problem(f"templates: {len(queue)} expected dialog(s) did not open")


def choose(box, value):
    index = box.findData(value)
    box.setCurrentIndex(index)
    return index >= 0


def assign(wizard, mapping):
    for table, (source, columns) in mapping.items():
        choose(wizard.source_boxes[table], source)
        for column, chosen in columns.items():
            choose(wizard.column_boxes[table, column], chosen)


def tab_state(window):
    return [(session.project.title, session.project.dirty, session.project.history.can_apply(),
             len(session.project.runs)) for session in window.sessions]


def run(smoke, window):
    """Raises nothing for a deviation: each one becomes a problem in the smoke report."""
    from . import templates
    from analisi.analysis_templates import read_template
    tag = smoke.language  # "en" or "it" in the full smoke, "en-dark"… in the dedicated one.
    folder = smoke.folder / f"templates-{tag}"
    original = write_fixtures(folder)
    lines = []
    expected = []
    window.error = lambda error: expected.append(str(error))

    def check(ok, text):
        if not ok:
            smoke.problem(f"templates: {text}")

    def unexpected(step):
        if expected:
            smoke.problem(f"templates: {step}: message shown: {expected[0]}")
        expected.clear()

    # A clean window: one empty tab.
    while len(window.sessions) > 1:
        window.sessions[len(window.sessions) - 1].project.dirty = False
        window.switch_project(window.sessions[len(window.sessions) - 1])
        window.close_project()
    window.project.dirty = False
    window.close_project()

    # 1. The original project, calculated from its layout.
    window.open_path(original)
    settle(smoke)
    window.open_sheet(("layout", 0))
    settle(smoke)
    smoke.shot(window, "templates-original-layout")
    check(slopes(window.project)[:1] == [4.0] and 1.0 in slopes(window.project), f"original slopes {slopes(window.project)}")
    unexpected("open original")
    project = window.project
    before = (project.dirty, project.path, original.read_bytes())
    target = folder / "procedura.tramatpl"
    for stale in folder.glob("*.tramatpl"):  # A folder used before starts without templates.
        stale.unlink()

    # 2. Save as template: close after choosing the name and seeing the preview, then save for real.
    def cancel_after_preview(dialog):
        dialog.file.setText(str(target))
        smoke.shot(dialog, "templates-save-confirm")
        return False

    alias = folder / "alias-del-progetto.tramatpl"
    try:
        alias.unlink(missing_ok=True)
        alias.symlink_to(original)
    except OSError:  # Windows without the right to create links: the project name itself is tried instead.
        alias = None
        lines.append("alias: symbolic links not available here, wrong suffix tried instead")

    def save_alias(dialog):
        dialog.file.setText(str(alias if alias is not None else original))  # The open project, through a link.
        dialog.accept()
        smoke.app.processEvents()
        check(dialog.problem.isVisible() and dialog.focusWidget() is dialog.file, "the open project was not refused")
        smoke.shot(dialog, "templates-save-error")
        dialog.file.setText(str(target))
        dialog.accept()
        return dialog.path is not None

    with driving(smoke, [cancel_after_preview]):
        window.save_template()
    settle(smoke)
    check(not target.exists(), "closing the confirmation wrote a file")
    with driving(smoke, [save_alias]):
        window.save_template()
    settle(smoke)
    unexpected("save template")
    check(target.exists(), "the template was not written")
    check((project.dirty, project.path, original.read_bytes()) == before, "saving the template changed the project")
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    check(SENTINEL not in text and '"schema": 1' in text, "the template holds observations or no schema 1")
    lines.append(f"template {target.name}: {len(text.encode('utf-8'))} bytes, sentinel absent: {SENTINEL not in text}")

    # 3. The new data as sheets of a second project, mapped in the assistant.
    window.new_project()
    for name in ("Campioni nuovi", "Controlli nuovi"):
        window.open_path(folder / f"{name}.csv", import_data=False)
        settle(smoke)
    check(list(window.project.tables) == ["Campioni nuovi", "Controlli nuovi"], f"sheets {list(window.project.tables)}")
    second = window.project
    second_state = (second.dirty, list(second.tables), [len(table.raw) for table in second.tables.values()])

    def wizard_errors(wizard):
        smoke.shot(wizard, "templates-assistant")
        assign(wizard, MAPPING)
        choose(wizard.column_boxes["Analisi α", "Y"], "Dose")  # Dose twice.
        wizard.accept()
        smoke.app.processEvents()
        box = wizard.column_boxes["Analisi α", "Y"]
        check(wizard.problem.isVisible() and wizard.focusWidget() in (box, wizard.column_boxes["Analisi α", "X"]),
              f"duplicate column: no error with focus ({wizard.problem.text()})")
        check(bool(wizard.focusWidget() and wizard.focusWidget().accessibleDescription()),
              "duplicate column: the focused field has no accessible description")
        smoke.shot(wizard, "templates-assistant-duplicate")
        choose(wizard.column_boxes["Analisi α", "Y"], "Segnale (mV)")
        choose(wizard.column_boxes["Controllo", "Signal"], None)
        wizard.column_boxes["Controllo", "Signal"].setCurrentIndex(0)
        wizard.accept()
        smoke.app.processEvents()
        check(wizard.problem.isVisible() and wizard.focusWidget() is wizard.column_boxes["Controllo", "Signal"],
              "empty field: no error with focus")
        smoke.shot(wizard, "templates-assistant-empty")
        return False  # Cancel: no tab.

    tabs = len(window.sessions)
    with driving(smoke, [wizard_errors]):
        window.new_from_template(target)
        settle(smoke)
    check(len(window.sessions) == tabs and window.project is second, "Cancel in the assistant created a tab")

    def wizard_ok(wizard):
        assign(wizard, MAPPING)
        smoke.shot(wizard, "templates-assistant-mapped")
        check("Extra" in wizard.summary.text(), "the ignored column Extra is not in the summary")
        wizard.accept()
        return wizard.mapping is not None

    started = time.perf_counter()
    with driving(smoke, [wizard_ok]):
        window.new_from_template(target)
        settle(smoke)
    lines.append(f"new project from template (2×4 rows, read + map + build + calculate): "
                 f"{time.perf_counter() - started:.2f} s")
    unexpected("new project")
    built = window.project
    check(len(window.sessions) == tabs + 1 and built is not second, "no new tab")
    check(built.path is None and built.origin is None and built.dirty, "the new project has a path or is clean")
    check(not built.history.can_apply(), "the new project has history")
    check((second.dirty, list(second.tables), [len(table.raw) for table in second.tables.values()]) == second_state,
          "the source project changed")
    window.open_sheet(("layout", 0))
    settle(smoke)
    smoke.shot(window, "templates-new-layout")
    check(slopes(built) == [6.0, 3.0, 5.0], f"new slopes {slopes(built)}")
    check(list(built.tables["Analisi α"].raw["Badge"]) == ["0003", "0004", "0005", "0006"], "text IDs changed")
    check(not built.tables["Analisi α"].excluded, "exclusions travelled")

    # 4. Save, reopen from the layout, edit a measure: the change reaches the layout.
    saved = folder / "Istanza.alab"
    with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(saved), "")):
        window.save(as_new=True)
    settle(smoke)
    window.close_project()
    window.open_path(saved)
    settle(smoke)
    window.open_sheet(("layout", 0))
    settle(smoke)
    reopened = window.project
    check(slopes(reopened) == [6.0, 5.0], f"reopened layout slopes {slopes(reopened)}")  # The two panels.
    window.open_sheet(("data", "Controllo"))
    model = window.sheet.model()
    model.setData(model.index(3, 1), "26")
    smoke.app.processEvents()
    settle(smoke)
    window.open_sheet(("layout", 0))
    settle(smoke)
    check(slopes(reopened)[-1] == 6.5, f"the edit did not propagate: {slopes(reopened)}")
    smoke.shot(window, "templates-reopened-edited")
    reopened.dirty = False

    # 5. Applied twice: identities never cross.
    first_ids = {run.uid for run in reopened.runs}  # The identities of the first application, saved and reopened.
    window.switch_project(next(s for s in window.sessions if s.project is second))
    with driving(smoke, [wizard_ok]):
        window.new_from_template(target)
        settle(smoke)
    again = window.project
    check(again is not second and not first_ids & {run.uid for run in again.runs}
          and not set(IDS) & {run.uid for run in again.runs}, "identities were reused")
    again.dirty = False
    unexpected("second application")

    # 6. Refusals: damaged templates, six projects, Cancel while building, Info out of scope.
    window.switch_project(next(s for s in window.sessions if s.project is second))
    good = target.read_text(encoding="utf-8")
    damaged = {"schema": folder / "schema-999.tramatpl", "duplicate": folder / "duplicate.tramatpl"}
    damaged["schema"].write_text(good.replace('"schema": 1', '"schema": 999', 1), encoding="utf-8")
    damaged["duplicate"].write_text(good.replace("{", '{"schema":1,', 1), encoding="utf-8")
    state = tab_state(window)
    for name, path in damaged.items():
        window.new_from_template(path)
        settle(smoke)
        smoke.app.processEvents()
        check(len(expected) == 1 and path.name in expected[0], f"damaged {name}: {expected}")
        lines.append(f"refused {path.name}: {expected[:1]}")
        expected.clear()
    check(tab_state(window) == state, "a damaged template changed a tab")

    while not window.sessions.full():
        window.new_project()
        window.project.dirty = True  # Not empty: the next template needs a tab of its own.
    window.new_from_template(target)
    settle(smoke)
    check(len(expected) == 1 and len(window.sessions) == 6, f"six projects: {expected}")
    lines.append(f"six tabs: {expected[:1]}")
    expected.clear()
    for session in list(window.sessions):
        if not session.project.tables and session.project.path is None:
            session.project.dirty = False
            window.switch_project(session)
            window.close_project()
    window.switch_project(next(s for s in window.sessions if s.project is second))

    gate = threading.Event()
    real = templates.instantiate_template

    def slow(*args, **kwargs):
        cancel = kwargs["cancel"]
        while not cancel.is_set() and not gate.wait(0.02):
            pass
        return real(*args, **kwargs)

    tabs, state = len(window.sessions), tab_state(window)
    with mock.patch.object(templates, "instantiate_template", slow), driving(smoke, [wizard_ok]):
        window.new_from_template(target)
        end = time.monotonic() + 30  # Read, assistant, then the build that waits for Cancel.
        while not (window.job is not None and window.job.label.startswith(templates.t("building")))\
                and time.monotonic() < end:
            smoke.app.processEvents()
            time.sleep(0.02)
        check(window.job is not None, "the build did not start")
        smoke.shot(window, "templates-building")
        window.cancel_calculation()
        settle(smoke)
    gate.set()
    check(len(window.sessions) == tabs and tab_state(window) == state, "Cancel while building created a tab")
    unexpected("cancel")

    window.open_path(original)
    settle(smoke)
    from analisi.info import InfoSheet
    project = window.project
    sheet = InfoSheet("Costanti", (("k", "2"),), table="Analisi α")
    project.update_info_sheets({**project.info_sheets, sheet.uid: sheet})
    project.set_formula("Analisi α", "Scaled2", '=Y*INFO("k")')

    def info_refused(dialog):
        check(not dialog.save_button.isEnabled() and "Scaled2" in dialog.preview.toPlainText(),
              "the Info formula did not block the template")
        smoke.shot(dialog, "templates-info-refused")
        return False

    with driving(smoke, [info_refused]):
        window.save_template()
    project.dirty = False
    unexpected("info")
    lines.append("tabs at the end: " + "; ".join(f"{title} dirty={dirty} runs={runs}"
                                                for title, dirty, _, runs in tab_state(window)))
    (smoke.folder / f"templates-{tag}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for session in window.sessions:
        session.project.dirty = False
    window.error = lambda error: smoke.problem(f"error shown: {error}")
    return lines


def measure(folder, rows=50_000, columns=20):
    """Cold and warm times of reading and applying a template to rows × columns source values (the engine
    calculation of the analyses is timed apart and not attributed to the template)."""
    from analisi.analysis_templates import instantiate_template, plan_template, read_template, write_template
    from analisi.data import Dataset
    from trama_qt.project import Project
    folder.mkdir(parents=True, exist_ok=True)
    names = [f"C{index}" for index in range(columns)]
    small = {"Wide": Dataset(pd.DataFrame({name: [1.0, 2.0] for name in names}),
                             formulas={"Sum": "=C0+C1"},
                             analyses=[("Linear regression", {"X": "C0", "Y": "Sum"})])}
    rng = np.random.default_rng(7)
    big_frame = pd.DataFrame(rng.normal(size=(rows, columns)), columns=names)
    big = {"Wide": Dataset(big_frame.copy(), formulas={"Sum": "=C0+C1"},
                           analyses=[("Linear regression", {"X": "C0", "Y": "Sum"})])}
    lines = []
    path_small, path_big = folder / "small.tramatpl", folder / "big.tramatpl"
    started = time.perf_counter()
    write_template(path_small, small)
    small_time = time.perf_counter() - started
    started = time.perf_counter()
    write_template(path_big, big)
    big_time = time.perf_counter() - started
    lines.append(f"save template 2 rows: {small_time * 1000:.1f} ms; {rows} rows: {big_time * 1000:.1f} ms; "
                 f"same bytes: {path_small.read_bytes() == path_big.read_bytes()}")
    source = {"New": big_frame.rename(columns=lambda name: f"src {name}")}
    mapping = {"Wide": ("New", {name: f"src {name}" for name in names})}
    for label in ("cold", "warm"):
        started = time.perf_counter()
        template = read_template(path_big)
        read_time = time.perf_counter() - started
        started = time.perf_counter()
        tables, layouts = instantiate_template(template, source, mapping)
        apply_time = time.perf_counter() - started
        project = Project()
        project.tables = tables
        project.runs = [run for title, dataset in tables.items() for run in Project.runs_for(title, dataset)]
        started = time.perf_counter()
        job = project.plan_refresh(project.runs)
        errors = project.apply_refresh(job, project.run_refresh(job))
        engine_time = time.perf_counter() - started
        lines.append(f"{label}: read {read_time * 1000:.1f} ms, apply {rows}×{columns} {apply_time * 1000:.1f} ms; "
                     f"engine calculation (not the template) {engine_time * 1000:.1f} ms, errors {errors}")
    plan = plan_template(big)
    lines.append(f"plan of the {rows}-row project: {len(plan.omissions)} omission(s), rows left out {plan.rows}")
    return lines


def run_dedicated(folder, languages=("en", "it"), modes=("light", "dark")):
    """``--only qt-analysis-templates``: the scenario in each language and theme, preferences untouched."""
    import traceback
    from analisi.i18n import active_language, set_language
    from . import theme
    from .smoke import Smoke
    from .window import MainWindow
    smoke = Smoke(folder)
    previous_language, previous_mode = active_language(), theme.STATE["mode"]
    notes = []
    try:
        for language in languages:
            for mode in modes:
                smoke.language = f"{language}-{mode}"
                set_language(language)
                theme.install_qt_translations(smoke.app, language)
                theme.set_mode(mode, smoke.app, remember=False)
                smoke.window = window = MainWindow()
                available = smoke.screen_rect(window)
                window.resize(min(1280, available.width()), min(800, available.height()))
                window.show()
                theme.keep_on_screen(window)
                smoke.app.processEvents()
                try:
                    notes += [f"[{language}-{mode}] {line}" for line in run(smoke, window)]
                except Exception:  # noqa: BLE001 - the report says what broke, then the next run starts.
                    smoke.problem("templates stopped:\n" + traceback.format_exc())
                finally:
                    for session in window.sessions:
                        session.project.dirty = False
                    window.close()
                    window.deleteLater()
                    smoke.app.processEvents()
        notes += ["", "Performance (50,000 × 20 source values):", *measure(Path(folder) / "perf")]
    finally:
        set_language(previous_language)
        theme.install_qt_translations(smoke.app, previous_language)
        theme.set_mode(previous_mode, smoke.app, remember=False)
    (Path(folder) / "templates-report.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    return smoke.report()
